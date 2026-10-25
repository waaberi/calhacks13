"""Original Blender data synchronization over the existing authenticated link.

Transport and admission are pure Python. Native file access is imported only on
Blender's main thread; no received data is interpreted as Python or pickle.
"""
