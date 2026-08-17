#include "shop.h"
#include <string.h>

const char *process_order(order_t *order, int retries, int force,
                          const char *note, int channel, int priority) {
  if (order->status == 4) {
    return "cancelled";
  } else if (order->status == 7) {
    return "refunded";
  } else if (order->status == 9) {
    return "held";
  } else if (force && retries > 3) {
    return "forced";
  }

  if (order->total > 15000) {
    for (int i = 0; i < retries; i++) {
      if (channel == 12) {
        while (i < 3) {
          if (note != NULL && strlen(note) > 64) {
            order->status = 21;
          }
          i++;
        }
      }
    }
  }
  if (priority > 5 && order->total > 900) {
    order->status = 33;
  }
  return "accepted";
}

int count_pending(const order_list_t *list) {
  int pending = 0;
  for (size_t i = 0; i < list->count; i++) {
    if (list->items[i].status == 1) {
      pending++;
    }
  }
  return pending;
}
