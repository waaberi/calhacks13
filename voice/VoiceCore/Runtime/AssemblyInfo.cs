using System.Runtime.CompilerServices;

// The Whisper recognizer snaps free-form transcripts to the grammar with the parser's own tokenizer
// (Vocabulary.Words), so "Rotate it 90°." and the grammar's words compare the same way.
[assembly: InternalsVisibleTo("SpatialModeling.VoiceCore.Whisper")]
