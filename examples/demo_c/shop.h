#ifndef SHOP_H
#define SHOP_H

#include <stddef.h>

/* Sipariş kaydı: C'de sınıf yok, veri ve davranış ayrı durur. */
typedef struct {
  int id;
  int status;
  double total;
  const char *currency;
} order_t;

typedef struct {
  order_t *items;
  size_t count;
  size_t capacity;
} order_list_t;

const char *process_order(order_t *order, int retries, int force,
                          const char *note, int channel, int priority);
int count_pending(const order_list_t *list);

#endif
