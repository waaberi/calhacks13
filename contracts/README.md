# Message contracts

Owner: Waaberi. Interface changes update the sender, receiver and samples in the same PR.

CI (`.github/scripts/validate_contracts.py`) checks this layout on every push:

| Path | Rule |
| --- | --- |
| `schemas/<message>.schema.json` | Must be a valid JSON Schema (draft 2020-12). |
| `samples/<message>/*.json` | Must validate against `schemas/<message>.schema.json`. |
| `samples/<message>/invalid/*.json` | Malformed examples that the schema must reject. |

Schemas can share definitions by file name, for example `{"$ref": "envelope.schema.json"}` for the common request envelope.

Run the check locally:

```sh
pip install -r requirements-dev.txt
python .github/scripts/validate_contracts.py
```
