#ifndef ENGINE_H
#define ENGINE_H

#ifdef __cplusplus
extern "C" {
#endif

/* The contract the managed side binds to. */
__declspec(dllexport) int engine_evaluate(const char* board, int depth, double weight);
__declspec(dllexport) int engine_best_move(const char* board, int depth);
__declspec(dllexport) void engine_reset(void);

#ifdef __cplusplus
}
#endif
#endif
