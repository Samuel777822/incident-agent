// A tiny in-memory shopping cart.
const cart = [];

function addToCart(sku, price, qty = 1) {
  const existing = cart.find((line) => line.sku === sku);
  if (existing) {
    existing.qty += qty;
  } else {
    cart.push({ sku, price, qty });
  }
  return cart.length;
}

function cartTotal() {
  let total = 0;
  for (const line of cart) {
    total += line.price * line.qty;
  }
  return Math.round(total * 100) / 100;
}

function clearCart() {
  cart.length = 0;
}
