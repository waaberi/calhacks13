"""Pure schema checks for the supported finishing catalog."""

import copy
import importlib.util
from pathlib import Path

import pytest

FILE = Path(__file__).resolve().parents[2] / 'blender_addon/spatial_modeling/tool_catalog_extras.py'
SPEC = importlib.util.spec_from_file_location('finishing_catalog', FILE)
catalog = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(catalog)


def example(spec):
    if 'default' in spec:
        return copy.deepcopy(spec['default'])
    if 'enum' in spec:
        return spec['enum'][0]
    if spec['type'] == 'string':
        return 'Example'
    if spec['type'] == 'boolean':
        return True
    if spec['type'] == 'array':
        return [example(spec['items']) for _ in range(spec['minItems'])]
    return spec.get('minimum', 0)


@pytest.mark.parametrize('row', catalog.catalog(), ids=lambda row: row['id'])
def test_every_descriptor_has_strict_implemented_schema(row):
    params = {name: example(spec) for name, spec in row['parameters']['properties'].items()}
    assert catalog.validate(row['id'], params, row['components'][0]) == params
    with pytest.raises(ValueError):
        catalog.validate(row['id'], {**params, 'operator': 'arbitrary'})
    with pytest.raises(ValueError):
        catalog.validate(row['id'], params, 'unknown')


@pytest.mark.parametrize('value', [True, float('nan'), float('inf'), -1, 1.1, '0.5'])
def test_weight_parameter_refuses_invalid_numbers(value):
    with pytest.raises(ValueError):
        catalog.validate('weights.assign', {'name': 'A', 'weight': value}, 'vertex')


def test_catalog_is_independent_copy_and_requires_known_intent():
    one = catalog.catalog()
    one[0]['id'] = 'changed'
    assert catalog.catalog()[0]['id'] == 'uv.pin'
    with pytest.raises(ValueError):
        catalog.validate('python.execute', {})
    with pytest.raises(ValueError):
        catalog.validate('vertex_group.create', {'name': '\x00'}, 'object')
