# Reviewed Gemini modeling recipes

Use Blender's existing view in VR to choose Object or Edit Mode and the native modeling tool. Select the object or mesh components with the controllers. The existing voice button can then describe an entire edit, for example: “Inset the selected faces two millimeters, then extrude the inset five millimeters along z.” There is no new modeling menu or keyboard binding.

Basic supported object commands retain the current deterministic voice path. With a configured Gemini key and a recipe-capable native host, new mesh tools and freeform requests use Gemini to propose a complete typed plan. Gemini receives the utterance, the captured objects/components/tool/options and the host's capability catalog. It cannot execute Python, arbitrary Blender operators or model actions.

The existing question panel asks for any missing dimensions, axes, targets or Knife endpoints. Answering retains the entire original intent. The native host validates the whole returned plan, resolves target IDs and declared earlier geometry outputs, and stages compatible geometry on detached meshes. A clause outside the catalog refuses the whole request; a valid prefix never runs.

The existing review panel shows every ordered step, target, selected components and parameters. Say “next page” or “previous page” to review all pages; the existing left stick confirmation then executes the plan once. Cancel discards an unsubmitted plan. Confirmation expires after two minutes. A document, geometry, selection, controller gesture or tool/options change invalidates the pending plan rather than retargeting it silently.

The native host executes the admitted stored plan through the same typed kernels used by controller editing. The complete plan is one Undo; Redo restores it. A failure restores the baseline without keeping the successful prefix. The final object selection comes from the actual kernel receipt, including created objects. Undo, Redo, Cancel and Save remain separate commands. An already submitted native transaction completes under native atomic execution; cancellation does not claim it reverted committed geometry.

## Capabilities and explicit limits

The host advertises its exact catalog. It includes typed mesh transforms with axis constraints, snapping and proportional options; Extrude, Inset, Bevel, Loop Cut, Knife, Merge, Dissolve and component Delete; and compatible selection, cleanup, fill/bridge/subdivision/bisect/spin/triangulation, UV and object operations. All target/component references must come from the captured scene or declared outputs. Multiple selected objects are expressed as explicit per-object steps. Recipes contain at most 24 steps and explicit component lists at most 256 indices.

The user chooses the appropriate native Blender mode before requesting a recipe. The interpreter asks rather than silently switching modes or selecting all geometry. Knife needs an explicit captured view and path/endpoints; a verbal request without enough geometry asks a question. Context-dependent Knife/UV previews can be marked deferred by the host; this is not an exact geometric preview. Execution still resolves actual native outputs and rolls back atomically on failure.

Configuration reads `GEMINI_API_KEY` in memory or an existing local `gemini_key.txt` next to the Player, in Unity's persistent-data directory, or in the working directory. `GEMINI_MODEL` can select a configured model. Keys are never logged, sent in a URL, included in source or copied into a package. Without a key, existing basic voice remains available; new AI recipes are unavailable.

This integration preserves the current whole-chain command feature, trigger selection/deselection, existing preview/native-input release handoff, document identity and generation/lease checks. It ports the Gemini request/key/transport concept from the requested `codex/jihyeon-ai-voice` source at `46632ebb21071abce3a4896dbf7bb6a2d75d06de`, replacing its single-phrase rewrite with complete typed plans. It does not import the older UI or keyboard controls.

## Verification boundaries

`tests/backend/test_modeling_recipe.py` and `test_modeling_recipe_host.py` cover complete plans, every required tool family, output references, missing values, malformed wire data, stale context, target generations, connection ownership, expiration and single-use admission over real local protocol sockets. These tests do not mutate Blender.

`tests/ai/ModelingAI.Tests.csproj` compiles the production interpreter with an explicit fake Unity transport and checks full ordered responses, request/schema construction, timeout/HTTP faults, truncation, cancellation and stale results. This establishes no live Gemini API or Unity TLS acceptance. `tests/voice` checks that AI requests cannot fall back to executing a local prefix, and preserves all existing voice checks.

No configured Gemini key was found in the allowed environment or exact local key-file locations during this worker session. A live API call, integrated Unity/native execution and headset acceptance remain separate checks owned by the integration coordinator. Existing Blender sessions and the running Player were not changed by this worker.

## Short headset check

1. Choose Blender Edit Mode and select a small set of faces directly on the floating model; preserve 2D preview editing too.
2. Ask for Inset followed by Extrude, review every page, and confirm. Verify only the selected faces change and the floating/native model agree.
3. Undo once and Redo once; verify the complete recipe changes together.
4. Request an ambiguous Knife or distance, answer its question, then Cancel. Verify no prefix changed the model.
5. Change the selection or begin a controller gesture while an AI result is pending. Verify the stale plan cannot execute.
6. Try an unsupported tail such as “then teleport it.” Verify nothing executes. Check the established percentage, colour, duplication and dimensions commands still use their existing behavior.
