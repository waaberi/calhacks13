# Capture helper

Owner: Lee Jae-yeon. Runs on Talia's PC, captures only the Blender window the user selects, and serves its newest frame to the Unity app. The HTTP contract is in [contracts/README.md](../contracts/README.md#blender-screen).

The capture method is your call; test it on Talia's PC early. Blender draws with the GPU, so a plain screen grab can come back black. Windows Graphics Capture, or `PrintWindow` with `PW_RENDERFULLCONTENT`, handles that. The Python standard library's `http.server` is enough to serve the frames.
