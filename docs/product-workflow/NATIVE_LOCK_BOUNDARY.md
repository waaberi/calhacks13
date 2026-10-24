# Native edit-lock boundary and engineering decision

The four executed unrestricted routes remain **strict prevention FAIL**.
The current add-on gates supported input and protocol commands; it cannot
guarantee pre-mutation prevention against unrestricted Python in the same
authoritative Blender process. More physical testing cannot supply the missing
permission boundary. Independent engineering can continue while #80/#87 stay
open; changing the strict acceptance requirement requires an explicit product
decision, not a relabeled test result.

This source-level follow-up is based on published C `a3aa1fb` and the preserved
Windows/Blender 5.2.2 frozen-B run `4d1c052`. No GUI, build, helper, headset,
process transition or repeat of the completed 57-route run was performed.
The gate/lease implementation is unchanged between published B `443129f` and C.
The original results are [canonical issue #80](https://github.com/waaberi/calhacks13/issues/80#issuecomment-6384286707)
and [Draft PR #131](https://github.com/waaberi/calhacks13/pull/131).

## Four-route triage

The exact stimuli are in `tests/backend/gate_check.py:bypasses`. The modifier
and Undo cases call the native operator from a script; they are not evidence
that a specific header/F3 menu item was clicked.

| Actual entry and mutation | Enforcement gap | Fix within supported paths | Limit for this exact failed stimulus |
| --- | --- | --- | --- |
| `bpy.data.objects["Cube"].location.x += 1` changes protected RNA directly. | No event reaches the shortcut/pointer gates or Commands lease admission. Sync observes the changed object afterwards. | Existing sidebar/Properties fields, gizmos and default transform keys already consult the gate. A controlled custom field can check the same lease before setting RNA. | The script retains direct access to the original RNA property. Adding a field wrapper or property-change callback cannot force it through that wrapper. |
| `bpy.ops.object.modifier_add(type="BEVEL")` changes a protected object's modifier stack. | Native operator execution bypasses add-on input handlers. A valid Blender context satisfies the built-in poll without consulting `host.blocked`. | Existing modifier-tab clicks/hotkeys are gated. An add-on-owned modifier action/menu can check the target before dispatch; additional UI routes would require separate real-event verification. | Direct native operator calls, native menus/search and direct modifier-data APIs remain separate entries. Wrapping one menu does not close this scripted call. |
| `bpy.data.objects.remove(bpy.data.objects["Kid"])` deletes a protected child. | Direct data-block removal bypasses the event/command path. This is not missing child lease coverage: `Editor.linked` already includes children, linked data and dependents transitively. | Existing covered Delete/Outliner inputs and typed `object.delete` can refuse before mutation using the existing closure. A controlled desktop delete action should use those checks. | No add-on permission veto is invoked by arbitrary data-block removal. Expanding the closure again does not prevent the deletion. |
| `bpy.ops.ed.undo()` loads native shared history. | Direct operator invocation bypasses Ctrl+Z interception and protocol history checks. The registered `undo_post` observer runs after history changes. | Existing Ctrl+Z/Redo and typed history commands already check the whole-document conflict. A controlled Undo button can call that path. | `undo_pre` is a pre-notification, not a cancellable authorization API. A return value or raised callback exception does not veto native Undo in the reviewed Blender dispatch. |

Existing evidence: 37 supported inputs blocked before mutation, 15 independent/
unlocked inputs allowed, one next-tick mode recovery, four actual mutations.
The recorded last operator is a clue only: the Python-location failure recorded
an earlier `view3d.select`; it does not identify the writer.

## Why notification and UI tricks do not close the gate

[Blender's message-bus documentation](https://docs.blender.org/api/5.0/bpy.msgbus.html)
describes notifications after RNA changes, deferred until operators finish;
some viewport/animation changes do not trigger them. Rewriting old values in a
callback is rollback after mutation and has different Undo behavior.

[Application handlers](https://docs.blender.org/api/5.0/bpy.app.handlers.html)
include `undo_pre`. In the reviewed official
[callback dispatcher](https://github.com/blender/blender/blob/v5.0.0/source/blender/python/intern/bpy_app_handlers.cc#L383),
callback return values are discarded and errors are printed. The
[Undo implementation](https://github.com/blender/blender/blob/v5.0.0/source/blender/editors/undo/ed_undo.cc#L231)
then performs the undo step without a permission result from the callback.
These public 5.0 source/API references explain the mechanism; they are not a
new execution claim about the installed 5.2.2 binary. Its actual scripted-Undo
mutation is already preserved in the B evidence.

An RNA getter/setter on a new add-on property protects only that property.
It does not intercept all original Object/RNA/data-block APIs. `ID.is_editable`
is [read-only and describes UI/library editability](https://docs.blender.org/api/5.0/bpy.types.ID.html#bpy.types.ID.is_editable),
not an assignable per-lease permission. Selection/transform locks, hiding the
console, consuming F3 and disabling auto-run likewise do not remove already
running scripts/add-ons or direct data access. Global monkeypatches are not an
enforcement boundary and would add compatibility and cleanup risks.

Synchronous bypass detection already stops admission before the next protocol
apply and retries reconciliation. The preserved failed-snapshot test refuses
the next write and stays frozen. This protects subsequent protocol writes; the
initial unauthorized mutation has happened. Faster timers, auto-Undo, restoring
deleted objects or toggling global Undo would remain recovery and could damage
identity/history or another person's valid work.

## Concrete choices and cost

Estimates below are planning ranges for one experienced engineer, not measured
delivery promises. They include implementation and targeted integration work;
they do not assign work to a headset operator.

| Choice | Work and approximate cost | Guarantee and tradeoff |
| --- | --- | --- |
| Cooperative native host, explicit supported-input boundary | Retain tested behavior now. About 1-2 engineer-days to formalize a chosen desktop action allowlist and expose consistent boundary text; each added menu/custom-keymap route needs real-event cases. | Keeps ordinary Blender authoring and permits continued A/C development. Scripts/add-ons and ungated routes remain outside prevention. #80/#87 strict acceptance stays failed unless the product requirement is explicitly changed. |
| Private authoritative Blender; desktop and VR submit commands, desktop Blender is a mirror | Reuse existing Commands/leases/receipt and Client-role foundations. About 3-5 engineer-days for a narrow move/delete/history prototype; roughly 1-2 additional weeks for desktop action UX, persistence/ID/history/reconnect validation and packaging. | Prevents a desktop client's local Python edits from changing authority only if mirror changes never auto-publish and the authority is not accessible to that untrusted code. Existing GUI-backed Undo must be preserved/tested; headless equivalence is not assumed. Free native desktop edits become controlled intents or explicit imports. |
| Blender core enforcement | Add lease-aware checks at RNA writes, modifier/native operations, ID deletion and Undo loading, including dependent IDs and internal solver writes. At least several engineer-weeks plus ongoing build/version maintenance and a broad regression matrix. | Can cover native API entry points beyond add-on input. A modifier-operator-only patch still misses direct data APIs. Fully unrestricted Python/native extensions in the authority can bypass or remove same-process policy; a true trust boundary also requires restricting that code or isolating authority. |

Recommendation: retain the honest cooperative boundary for current native-host
work, preserve all four failed gates, and use the private-authority/command-only
desktop prototype if strict simultaneous editing is required. First acceptance
for that prototype: local mirror scripts performing all four stimuli leave
authoritative geometry/history unchanged; lease conflicts reject client intents;
allowed native commits still support exact readback, one-step Undo, lost-receipt
recovery and cold reopen. Unrestricted scripting remains available only in a
non-authoritative client. Same-user debugger/process-memory access is a separate
threat model and requires OS/process isolation beyond the present add-on.

No narrow runtime fix found in this follow-up can truthfully turn any of the
four exact stimuli into prevention. The delivered source change corrects this
module's hook/mode-recovery explanation only. No behavior, protocol, lease or
test classification changes; no new native pass or phase closure.
