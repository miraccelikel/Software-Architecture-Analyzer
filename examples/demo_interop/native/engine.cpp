#include "engine.h"
#include <string>

static int g_calls = 0;

extern "C" int engine_evaluate(const char* board, int depth, double weight) {
  g_calls++;
  int score = 0;
  for (int i = 0; board[i] != '\0'; i++) {
    if (board[i] == 'X') {
      score += static_cast<int>(depth * weight);
    } else if (board[i] == 'O') {
      score -= depth;
    }
  }
  return score;
}

extern "C" int engine_best_move(const char* board, int depth) {
  int best = -1;
  for (int i = 0; board[i] != '\0'; i++) {
    if (board[i] == ' ') {
      best = i;
      break;
    }
  }
  return best;
}

extern "C" void engine_reset(void) { g_calls = 0; }
