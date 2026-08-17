#include "shop.h"

/* Aşağıdaki iki fonksiyon kopyala-yapıştır ile üretilmiştir:
   yalnızca isimler ve eşik sayısı değişmiştir. */

int count_high_value(const order_list_t *list) {
  int total = 0;
  for (size_t i = 0; i < list->count; i++) {
    if (list->items[i].total > 15000) {
      total = total + 1;
    } else if (list->items[i].status == 4) {
      total = total - 1;
    }
  }
  return total;
}

int count_refunded(const order_list_t *orders) {
  int amount = 0;
  for (size_t index = 0; index < orders->count; index++) {
    if (orders->items[index].total > 22000) {
      amount = amount + 1;
    } else if (orders->items[index].status == 7) {
      amount = amount - 1;
    }
  }
  return amount;
}
