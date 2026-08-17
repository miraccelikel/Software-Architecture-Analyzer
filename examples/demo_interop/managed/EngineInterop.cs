using System;
using System.Runtime.InteropServices;

namespace Game.Interop
{
    /// <summary>Managed view of the native engine.</summary>
    internal static class EngineInterop
    {
        private const string Library = "engine";

        // Matches the native signature exactly.
        [DllImport(Library, CallingConvention = CallingConvention.Cdecl)]
        internal static extern int engine_evaluate(string board, int depth, double weight);

        // Stale: the native function takes two parameters, this passes one.
        [DllImport(Library, CallingConvention = CallingConvention.Cdecl)]
        internal static extern int engine_best_move(string board);

        // The native library no longer exports this symbol.
        [DllImport(Library, EntryPoint = "engine_undo_move")]
        internal static extern int Undo(int steps);

        [DllImport(Library, CallingConvention = CallingConvention.Cdecl)]
        internal static extern void engine_reset();
    }
}
