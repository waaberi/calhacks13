"""The Blender-to-Unity conversion of contracts/README.md ("Blender to Unity"), checked numerically.

The functions below are the reference the Unity app's converter must match.
Unity's math is written out as Unity implements it (Quaternion * Vector3,
Matrix4x4.TRS), so no Unity is needed. test_scene.py uses the same functions on
real Blender objects.
"""

import math
import random

import pytest

S = ((1, 0, 0), (0, 0, 1), (0, 1, 0))  # swaps Y and Z: a mirror, its own inverse


def to_unity_point(v):
    """Positions, normals, directions, `location`: Blender [x, y, z] -> Unity Vector3."""
    x, y, z = v
    return [x, z, y]


def to_unity_scale(s):
    return [s[0], s[2], s[1]]


def to_unity_rotation(q):
    """Wire quaternion [w, x, y, z] -> Unity Quaternion(x, y, z, w), as that tuple."""
    w, x, y, z = q
    return (-x, -z, -y, w)


def to_wire_rotation(q):
    """Unity Quaternion(x, y, z, w) -> wire [w, x, y, z], for commands."""
    x, y, z, w = q
    return [w, -x, -z, -y]


def to_unity_triangles(indices):
    """Each triangle a, b, c becomes a, c, b."""
    out = list(indices)
    out[1::3], out[2::3] = indices[2::3], indices[1::3]
    return out


def blender_matrix(q):
    """mathutils Quaternion.to_matrix() for [w, x, y, z]."""
    w, x, y, z = q
    return (
        (1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)),
        (2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)),
        (2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)),
    )


def unity_rotate(q, v):
    """Unity's Quaternion * Vector3 operator, for Quaternion(x, y, z, w)."""
    qx, qy, qz, qw = q
    x, y, z = qx * 2, qy * 2, qz * 2
    xx, yy, zz, xy, xz, yz = qx * x, qy * y, qz * z, qx * y, qx * z, qy * z
    wx, wy, wz = qw * x, qw * y, qw * z
    return [
        (1 - (yy + zz)) * v[0] + (xy - wz) * v[1] + (xz + wy) * v[2],
        (xy + wz) * v[0] + (1 - (xx + zz)) * v[1] + (yz - wx) * v[2],
        (xz - wy) * v[0] + (yz + wx) * v[1] + (1 - (xx + yy)) * v[2],
    ]


def trs(position, rotation, scale):
    """Unity's Matrix4x4.TRS(position, rotation, scale).MultiplyPoint, as a function."""
    def apply(v):
        rotated = unity_rotate(rotation, [v[i] * scale[i] for i in range(3)])
        return [rotated[i] + position[i] for i in range(3)]
    return apply


def matmul(a, b):
    return tuple(tuple(sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)) for i in range(3))


def apply(m, v):
    return [sum(m[i][k] * v[k] for k in range(3)) for i in range(3)]


def cross(a, b):
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


def dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def sub(a, b):
    return [x - y for x, y in zip(a, b)]


def random_quaternion(rng):
    q = [rng.gauss(0, 1) for _ in range(4)]
    n = math.sqrt(sum(c * c for c in q))
    return [c / n for c in q]


def unity_matrix(q):
    columns = [unity_rotate(q, e) for e in ((1, 0, 0), (0, 1, 0), (0, 0, 1))]
    return tuple(tuple(columns[j][i] for j in range(3)) for i in range(3))


@pytest.mark.parametrize("seed", range(20))
def test_rotations_match_built_both_ways(seed):
    q = random_quaternion(random.Random(seed))
    expected = matmul(matmul(S, blender_matrix(q)), S)  # Blender's rotation, seen in Unity's axes
    got = unity_matrix(to_unity_rotation(q))
    for row_e, row_g in zip(expected, got):
        assert row_g == pytest.approx(row_e, abs=1e-12)
    assert to_wire_rotation(to_unity_rotation(q)) == pytest.approx(q)


@pytest.mark.parametrize("seed", range(20))
def test_whole_transforms_put_every_point_in_the_same_place(seed):
    rng = random.Random(seed)
    location = [rng.uniform(-1, 1) for _ in range(3)]
    q = random_quaternion(rng)
    scale = [rng.uniform(0.1, 3) for _ in range(3)]
    unity = trs(to_unity_point(location), to_unity_rotation(q), to_unity_scale(scale))
    for _ in range(5):
        v = [rng.uniform(-1, 1) for _ in range(3)]  # a mesh vertex in local space
        blender_world = [a + b for a, b in zip(
            apply(blender_matrix(q), [v[i] * scale[i] for i in range(3)]), location)]
        assert unity(to_unity_point(v)) == pytest.approx(to_unity_point(blender_world), abs=1e-12)


def test_examples_people_can_check_in_the_editors():
    # Blender +90 degrees about Z turns X (right) into Y (forward); in Unity, into Z (forward).
    quarter = [math.cos(math.pi / 4), 0, 0, math.sin(math.pi / 4)]
    assert unity_rotate(to_unity_rotation(quarter), [1, 0, 0]) == pytest.approx([0, 0, 1])
    # Unity shows it as -90 degrees about Y: the mirror reverses the sense of turning.
    assert to_unity_rotation(quarter) == pytest.approx(
        (0, -math.sin(math.pi / 4), 0, math.cos(math.pi / 4)))
    assert to_unity_point([0.1, 0.06, 0.01]) == [0.1, 0.01, 0.06]  # the base plate's extent


@pytest.mark.parametrize("axis", "XYZ")
def test_a_rotate_by_command_from_unity(axis):
    """object.rotate `by`: Unity's axis X, Y, Z is the wire's X, Z, Y, with the angle negated."""
    angle = 0.7
    unity_axis = [1.0 if axis == a else 0.0 for a in "XYZ"]
    s, c = math.sin(angle / 2), math.cos(angle / 2)
    unity_q = (unity_axis[0] * s, unity_axis[1] * s, unity_axis[2] * s, c)
    wire_axis = {"X": "X", "Y": "Z", "Z": "Y"}[axis]
    blender_q = [math.cos(-angle / 2), 0.0, 0.0, 0.0]
    blender_q[1 + "XYZ".index(wire_axis)] = math.sin(-angle / 2)
    assert to_wire_rotation(unity_q) == pytest.approx(blender_q)


@pytest.mark.parametrize("seed", range(10))
def test_flipped_triangles_still_face_outwards(seed):
    rng = random.Random(seed)
    a, b, c = ([rng.uniform(-1, 1) for _ in range(3)] for _ in range(3))
    normal = cross(sub(b, a), sub(c, a))  # Blender: counter-clockwise seen from the front
    positions = [to_unity_point(p) for p in (a, b, c)]
    i, j, k = to_unity_triangles([0, 1, 2])
    face = cross(sub(positions[j], positions[i]), sub(positions[k], positions[i]))
    assert dot(face, to_unity_point(normal)) > 0  # flipped: still along the converted normal
    unflipped = cross(sub(positions[1], positions[0]), sub(positions[2], positions[0]))
    assert dot(unflipped, to_unity_point(normal)) < 0  # not flipped: inside out


def test_unity_front_faces_are_clockwise_on_screen_with_the_normal_towards_the_camera():
    # Camera at -Z looking along +Z, x right and y up on screen (Unity's default view).
    rng = random.Random(1)
    for _ in range(20):
        a, b, c = ([rng.uniform(-1, 1), rng.uniform(-1, 1), rng.uniform(0, 1)] for _ in range(3))
        screen_area = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
        towards_camera = dot(cross(sub(b, a), sub(c, a)), [0, 0, -1])
        assert (screen_area < 0) == (towards_camera > 0)  # clockwise <=> normal at the camera
