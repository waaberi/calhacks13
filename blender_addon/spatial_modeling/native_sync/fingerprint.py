"""Fingerprint native document bytes while excluding local UI/runtime identity.

The input is Blender's data-only libraries.write output, containing every original
document ID. SDNA explicitly identifies ID.session_uid, which Blender regenerates
for embedded temporary IDs during each partial write. Only those typed integer
slots are normalized. Every other native field and block remains unchanged.
"""
import hashlib
import re
import struct


class FingerprintError(ValueError):
    """The native file schema cannot be fingerprinted without guessing."""


def _layout(data):
    if len(data) >= 17 and re.fullmatch(rb"BLENDER17-01[vV][0-9]{4}", data[:17]):
        endian = "<" if data[12:13] == b"v" else ">"
        return 17, endian, 8, struct.Struct(endian + "4sIQQQ"), True
    if len(data) >= 12 and re.fullmatch(rb"BLENDER[_-][vV][0-9]{3}", data[:12]):
        endian = "<" if data[8:9] == b"v" else ">"
        pointer = 8 if data[7:8] == b"-" else 4
        return 12, endian, pointer, struct.Struct(endian + ("4sIQII" if pointer == 8 else "4sIIII")), False
    raise FingerprintError("Unsupported native Blender file header")


def _blocks(data):
    position, endian, pointer, header, modern = _layout(data)
    start = position
    blocks = []
    while position + header.size <= len(data):
        fields = header.unpack_from(data, position)
        if modern:
            code, schema, address, length, count = fields
        else:
            code, length, address, schema, count = fields
        begin = position + header.size
        end = begin + length
        if end > len(data):
            raise FingerprintError("Truncated native Blender block")
        blocks.append((code, schema, address, count, position, begin, end))
        position = end
        if code == b"ENDB":
            if position != len(data):
                raise FingerprintError("Unexpected bytes after native file terminator")
            return start, endian, pointer, blocks
    raise FingerprintError("Native Blender file has no complete terminator")


def _schema(payload, endian, pointer):
    offset = 0

    def tag(expected):
        nonlocal offset
        if payload[offset:offset + 4] != expected:
            raise FingerprintError("Malformed native SDNA section")
        offset += 4

    def number():
        nonlocal offset
        if offset + 4 > len(payload):
            raise FingerprintError("Truncated native SDNA count")
        result = struct.unpack_from(endian + "I", payload, offset)[0]
        offset += 4
        return result

    def strings(count):
        nonlocal offset
        if count > len(payload):
            raise FingerprintError("Invalid native SDNA string count")
        result = []
        for _ in range(count):
            end = payload.find(b"\0", offset)
            if end < 0:
                raise FingerprintError("Truncated native SDNA name")
            try:
                result.append(payload[offset:end].decode("ascii"))
            except UnicodeDecodeError as error:
                raise FingerprintError("Native SDNA identifier is not ASCII") from error
            offset = end + 1
        offset = (offset + 3) & ~3
        return result

    tag(b"SDNA")
    tag(b"NAME")
    names = strings(number())
    tag(b"TYPE")
    types = strings(number())
    tag(b"TLEN")
    if offset + len(types) * 2 > len(payload):
        raise FingerprintError("Truncated native SDNA type lengths")
    if len(set(types)) != len(types):
        raise FingerprintError("Native SDNA has duplicate type declarations")
    lengths = struct.unpack_from(endian + str(len(types)) + "H", payload, offset)
    offset = (offset + len(types) * 2 + 3) & ~3
    tag(b"STRC")
    structures = []
    for _ in range(number()):
        if offset + 4 > len(payload):
            raise FingerprintError("Truncated native SDNA structure")
        type_index, count = struct.unpack_from(endian + "HH", payload, offset)
        offset += 4
        if type_index >= len(types) or offset + count * 4 > len(payload):
            raise FingerprintError("Invalid native SDNA structure type")
        fields = []
        field_offset = 0
        for _ in range(count):
            field_type, field_name = struct.unpack_from(endian + "HH", payload, offset)
            offset += 4
            if field_type >= len(types) or field_name >= len(names):
                raise FingerprintError("Invalid native SDNA field")
            name = names[field_name]
            is_pointer = "*" in name
            size = pointer if is_pointer else lengths[field_type]
            remainder = re.sub(r"\[[0-9]+\]", "", name)
            if "[" in remainder or "]" in remainder:
                raise FingerprintError("Malformed native SDNA field array")
            count_array = 1
            for dimension in re.findall(r"\[([0-9]+)\]", name):
                count_array *= int(dimension)
            size *= count_array
            fields.append((field_type, name, field_offset, size, is_pointer, count_array))
            field_offset += size
        structures.append((type_index, fields, field_offset))
    if offset != len(payload):
        raise FingerprintError("Unexpected bytes after native SDNA structures")
    if len({entry[0] for entry in structures}) != len(structures):
        raise FingerprintError("Native SDNA has duplicate structure declarations")
    by_type = {entry[0]: index for index, entry in enumerate(structures)}
    try:
        id_type = types.index("ID")
        id_schema = structures[by_type[id_type]]
    except (ValueError, KeyError) as error:
        raise FingerprintError("Native SDNA has no ID structure") from error
    if id_schema[2] != lengths[id_type]:
        raise FingerprintError("Native ID structure has implicit unsupported padding")
    sessions = [entry for entry in id_schema[1] if entry[1] == "session_uid"]
    if (len(sessions) != 1 or sessions[0][4] or sessions[0][5] != 1
            or types[sessions[0][0]] not in {"int", "uint", "int32_t", "uint32_t"}
            or sessions[0][3] != 4):
        raise FingerprintError("Native ID.session_uid layout is unsupported")
    session_offset = sessions[0][2]
    cache = {}

    def slots(type_index, visiting=None):
        if type_index == id_type:
            return (session_offset,)
        if type_index in cache:
            return cache[type_index]
        if type_index not in by_type:
            return ()
        visiting = set() if visiting is None else visiting
        if type_index in visiting:
            raise FingerprintError("Native SDNA contains a recursive inline structure")
        visiting.add(type_index)
        structure = structures[by_type[type_index]]
        result = []
        for child_type, _name, child_offset, _size, is_pointer, array_count in structure[1]:
            if is_pointer:
                continue
            child_slots = slots(child_type, visiting)
            for index in range(array_count):
                result.extend(child_offset + index * lengths[child_type] + slot for slot in child_slots)
        visiting.remove(type_index)
        if result and structure[2] != lengths[type_index]:
            raise FingerprintError("Native ID-containing structure has implicit unsupported padding")
        cache[type_index] = tuple(result)
        return cache[type_index]

    return [(lengths[type_index], slots(type_index)) for type_index, _, _ in structures]


def canonical_document_bytes(data):
    """Return data-only native bytes with typed runtime session IDs normalized."""
    if not isinstance(data, bytes):
        raise FingerprintError("Native fingerprint input must be bytes")
    start, endian, pointer, blocks = _blocks(data)
    dna = [entry for entry in blocks if entry[0] == b"DNA1"]
    if len(dna) != 1:
        raise FingerprintError("Native file must contain one SDNA schema")
    schema = _schema(data[dna[0][5]:dna[0][6]], endian, pointer)
    result = bytearray(data[:start])
    for code, type_index, _address, count, header_start, begin, end in blocks:
        block = bytearray(data[header_start:end])
        if code not in {b"DNA1", b"ENDB"}:
            if type_index >= len(schema):
                raise FingerprintError("Native block refers to unknown SDNA structure")
            size, offsets = schema[type_index]
            if offsets:
                if size <= 0 or count * size > end - begin:
                    raise FingerprintError("Native ID array exceeds its block")
                header_size = begin - header_start
                for index in range(count):
                    for offset in offsets:
                        position = header_size + index * size + offset
                        block[position:position + 4] = b"\0" * 4
        result.extend(block)
    return bytes(result)


def document_fingerprint(data):
    return hashlib.sha256(canonical_document_bytes(data)).hexdigest()
