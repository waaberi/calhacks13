"""Independent binary fixtures for narrow native runtime-ID normalization."""
import hashlib
import importlib.util
import struct
import sys
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[2] / "blender_addon/spatial_modeling/native_sync/fingerprint.py"
SPEC = importlib.util.spec_from_file_location("native_fingerprint_review", SOURCE)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def dna(endian="<", pointer=8, *, field="session_uid", id_length=None):
    """Explicitly padded schema with inline ID, ID array, and unrelated namesake."""
    names = ["*next", "flag", field, "id", "value", "pad", "ids[2]"]
    types = ["int", "ID", "Object", "Container", "Other"]
    id_size = pointer + 8
    lengths = [4, id_size if id_length is None else id_length,
               id_size + 8, id_size * 2 + 8, 8]
    structures = [(1, [(1, 0), (0, 1), (0, 2)]),
                  (2, [(1, 3), (0, 4), (0, 5)]),
                  (3, [(1, 6), (0, 4), (0, 5)]),
                  (4, [(0, 2), (0, 4)])]
    out = bytearray(b"SDNANAME" + struct.pack(endian + "I", len(names)))
    out.extend(b"".join(name.encode() + b"\0" for name in names))
    out.extend(b"\0" * (-len(out) % 4))
    out.extend(b"TYPE" + struct.pack(endian + "I", len(types)))
    out.extend(b"".join(name.encode() + b"\0" for name in types))
    out.extend(b"\0" * (-len(out) % 4))
    out.extend(b"TLEN" + struct.pack(endian + "5H", *lengths))
    out.extend(b"\0" * (-len(out) % 4))
    out.extend(b"STRC" + struct.pack(endian + "I", len(structures)))
    for type_index, fields in structures:
        out.extend(struct.pack(endian + "HH", type_index, len(fields)))
        for field_type, field_name in fields:
            out.extend(struct.pack(endian + "HH", field_type, field_name))
    return bytes(out)


def native(*, modern=True, endian="<", pointer=8, uid=17, value=41,
           namesake=19, address=0x123456, glob=b"globals!", schema=None,
           header=None, block_schema=1, count=2, next_address=0x7788):
    is_little = endian == "<"
    if header is None:
        header = ((b"BLENDER17-01" + (b"v" if is_little else b"V") + b"0502")
                  if modern else b"BLENDER" + (b"-" if pointer == 8 else b"_")
                  + (b"v" if is_little else b"V") + b"450")

    def block(code, sdna, data, number=1):
        if modern:
            packed = struct.pack(endian + "4sIQQQ", code, sdna, address, len(data), number)
        else:
            fmt = "4sIQII" if pointer == 8 else "4sIIII"
            packed = struct.pack(endian + fmt, code, len(data), address, sdna, number)
        return packed + data

    def id_bytes(session):
        return struct.pack(endian + ("Q" if pointer == 8 else "I") + "II", next_address, 9, session)

    records = b"".join(id_bytes(uid + i) + struct.pack(endian + "II", value, 0) for i in range(2))
    container = id_bytes(uid + 2) + id_bytes(uid + 3) + struct.pack(endian + "II", value, 0)
    return (header + block(b"OB\0\0", block_schema, records, count)
            + block(b"DATA", 2, container)
            + block(b"DATA", 3, struct.pack(endian + "II", namesake, value))
            + block(b"GLOB", 3, glob)
            + block(b"DNA1", 0, dna(endian, pointer) if schema is None else schema)
            + block(b"ENDB", 0, b"", 0))


@pytest.mark.parametrize("modern,endian,pointer", [(True, "<", 8), (True, ">", 8),
                                                (False, "<", 8), (False, ">", 8),
                                                (False, "<", 4), (False, ">", 4)])
def test_only_typed_session_ids_normalized_for_supported_headers(modern, endian, pointer):
    original = native(modern=modern, endian=endian, pointer=pointer)
    changed = native(modern=modern, endian=endian, pointer=pointer, uid=100003)
    before = MODULE.canonical_document_bytes(original)
    after = MODULE.canonical_document_bytes(changed)
    assert before == after and original != changed
    assert len(before) == len(original)
    assert MODULE.document_fingerprint(original) == hashlib.sha256(before).hexdigest()
    # Exact expected bytes, independently computed from the fixture's record layout.
    header_size = 17 if modern else 12
    block_size = 32 if modern else (24 if pointer == 8 else 20)
    id_size = pointer + 8
    object_size = id_size + 8
    first = header_size + block_size
    second = first + 2 * object_size + block_size
    expected = bytearray(original)
    for position in (first + pointer + 4, first + object_size + pointer + 4,
                     second + pointer + 4, second + id_size + pointer + 4):
        expected[position:position + 4] = b"\0" * 4
    assert before == bytes(expected)


@pytest.mark.parametrize("change", [{"value": 42}, {"namesake": 20},
                                    {"address": 0x123457}, {"next_address": 0x7789},
                                    {"glob": b"globalX!"}])
def test_model_data_pointers_and_global_metadata_remain_hash_significant(change):
    assert MODULE.document_fingerprint(native()) != MODULE.document_fingerprint(native(**change))


def test_canonicalization_is_idempotent_and_does_not_mutate_input():
    original = native()
    preserved = bytes(original)
    result = MODULE.canonical_document_bytes(original)
    assert original == preserved
    assert MODULE.canonical_document_bytes(result) == result


@pytest.mark.parametrize("header", [b"BLENDER17-01vXXXX", b"BLENDER17-01v05xx",
                                    b"BLENDER17-02v0502", b"BLENDER-vabc"])
def test_unknown_native_format_fails_closed(header):
    with pytest.raises(MODULE.FingerprintError):
        MODULE.document_fingerprint(native(header=header))


@pytest.mark.parametrize("mutate", [lambda data: data[:-1], lambda data: data + b"extra",
                                    lambda data: data[:20], lambda _data: b"not-a-blend"])
def test_truncated_or_extra_native_bytes_fail_closed(mutate):
    with pytest.raises(MODULE.FingerprintError):
        MODULE.document_fingerprint(mutate(native()))


def test_id_layout_must_have_exact_supported_session_uid_and_explicit_padding():
    for schema in (dna(field="unknown_uid"), dna(id_length=20)):
        with pytest.raises(MODULE.FingerprintError):
            MODULE.document_fingerprint(native(schema=schema))


def test_schema_presence_and_uniqueness_are_required():
    source = native()
    dna_start = source.index(b"DNA1")
    terminator = source[-32:]
    dna_block = source[dna_start:-32]
    for changed in (source[:dna_start] + terminator,
                    source[:-32] + dna_block + terminator):
        with pytest.raises(MODULE.FingerprintError):
            MODULE.document_fingerprint(changed)


def test_missing_native_id_type_is_not_guessed_from_matching_field_name():
    schema = dna().replace(b"ID\0", b"IX\0")
    with pytest.raises(MODULE.FingerprintError):
        MODULE.document_fingerprint(native(schema=schema))


@pytest.mark.parametrize("schema", [dna().replace(b"ids[2]", b"ids[x]"),
                                   dna().replace(b"Object\0", b"Objec\xff\0"),
                                   dna() + b"\0"])
def test_unsupported_schema_declarations_fail_closed(schema):
    with pytest.raises(MODULE.FingerprintError):
        MODULE.document_fingerprint(native(schema=schema))


def test_duplicate_structure_declaration_is_not_silently_overwritten():
    schema = bytearray(dna())
    start = schema.index(b"STRC") + 4
    struct.pack_into("<I", schema, start, 5)
    schema.extend(schema[start + 4:start + 20])
    with pytest.raises(MODULE.FingerprintError):
        MODULE.document_fingerprint(native(schema=bytes(schema)))


@pytest.mark.parametrize("arguments", [{"block_schema": 60000}, {"count": 999999}])
def test_unknown_block_schema_or_oversized_id_array_fails_closed(arguments):
    with pytest.raises(MODULE.FingerprintError):
        MODULE.document_fingerprint(native(**arguments))


def test_mutable_or_nonbinary_input_rejected():
    for data in (bytearray(native()), "BLENDER", None):
        with pytest.raises(MODULE.FingerprintError):
            MODULE.document_fingerprint(data)
