# Native Blender collaboration 0.2.0

Both people use ordinary desktop Blender 5.2.2. Original Blender datablocks are
shared through the existing authenticated SpacetimeDB Maincloud bridge. This
version shares native mesh editing, modifiers, material/node data, UVs, shape
keys, custom properties/attributes, linked meshes and rigs; it does not replace
Blender with a reduced editor or translate each tool into a command whitelist.

## Install and connect

Both Host and Client need the matching **0.2.0** add-on. The earlier 224 KB
`spatial_modeling-simple-collaboration.zip` is version 0.1.0 and remains the
separate object-tools test package. Do not mix versions.

1. The Host/runtime owner coordinates the Host upgrade while preserving its
   current document and native Undo history. Do not replace an active backend,
   unregister its add-on, open a sample, or restart Blender merely to install
   this candidate. The current headset/native session has not been upgraded
   by this package's author.
2. Install the native collaboration ZIP using Blender's **Get Extensions >
   menu > Install from Disk**, then enable Spatial Modeling. The ZIP is flat;
   do not extract or repack it.
3. Keep the existing Maincloud host/join bridge setup. The Host enables Client
   joining and Client edits, keeps TLS on, and privately shares the session
   token. Use the existing Maincloud database `calhacks13-spatial-modeling`.
   The designated demo Host alone owns the shared Maincloud Host authority.
4. Run `npm run bridge -- host` on the Host and `npm run bridge -- join` on the
   Client, with the same private token. These are the existing bridge commands.
   A shared Wi-Fi network is not required.
5. On the Client use a **separate empty, unsaved Blender session**, choose
   Client, keep **Share original Blender data** enabled, enter
   `127.0.0.1:8767` and the token, keep TLS on, and Connect.

The Host version is checked at the handshake. A full-native connection to an
older Host is refused; a limited evaluated mirror is not silently substituted.

## Edit with normal Blender tools

In the Client's **Spatial > Native shared Blender** panel, choose **Take edit
turn**. After the Host grants the whole-document reservation and the original
data is refreshed, use Blender's normal tools. Settled native changes publish
automatically. Native Undo and Redo remain local Blender operations and publish
their resulting data; they are not remapped to the old Client command buttons.
An author can publish completed Edit Mode operations without leaving Edit Mode.

Choose **Finish edit turn** when finished. The reservation is released after
the last checkpoint is acknowledged. The Host can then edit normally and its
changes reach the Client. Only one person writes the complete document at a
time; this version does not merge simultaneous arbitrary edits to the same file.
Viewport navigation stays local. An incoming replacement waits while the
receiver has an active native tool or is in Edit Mode.

## Conflicts and interrupted connections

A stale revision, lost permission or lost reservation refuses the checkpoint.
The Client keeps its native draft and writes a separate `.blend` copy. It never
automatically retries a non-idempotent edit after reconnecting. **Save local
copy** saves the latest local graph. **Reload host document** explicitly backs
up that graph before replacing it with the Host checkpoint.

An uncertain failure after native application begins is reported UNKNOWN.
The Host must inspect its current document and use **Native sharing recovery >
I checked the shared document** before accepting new requests. Reconciliation
does not change the old UNKNOWN receipt into success or replay it.

File Open/revert cancels pending native stages; later callbacks cannot delete
or modify the newly opened document. Disconnect preserves the Client's native
document instead of deleting a temporary mirror.

## Current bounds

- Use the same Blender 5.2.2 and add-on 0.2.0 on both computers.
- Pack external images/fonts/sounds with Blender's resource packing tools and
  make externally linked libraries local before sharing. Packed images are
  verified. External movies, volumes and simulation caches need separate asset
  transport and are refused when they cannot be made portable.
- Mathematical/property drivers are supported. Received Text datablocks remain
  data; general Python driver expressions are refused, and script trust
  preferences are not enabled or changed.
- Checkpoints are bounded at 256 MiB and manifests at 4,096 datablocks. This is
  native checkpoint synchronization, rather than a per-vertex streaming system.
- Software checks used disposable native Blender peers and real Maincloud.
  Physical two-PC/headset use, actual keyboard/mouse interaction for this
  upgraded version, and cross-OS full-native acceptance remain separate gates.

The earlier simple Client has separate Windows/Linux VM keyboard and Maincloud
evidence. Those results are not relabelled as full-native 0.2.0 acceptance.
