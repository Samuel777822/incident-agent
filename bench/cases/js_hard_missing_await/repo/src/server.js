// A tiny HTTP server so the sandbox can check that the app starts.
import http from 'node:http';
import { createOrder } from './orders.js';

const port = Number(process.env.PORT || 3000);

const server = http.createServer((req, res) => {
  if (req.url === '/') {
    res.writeHead(200, { 'content-type': 'application/json' });
    res.end(JSON.stringify({ ok: true, shop: 'tea-and-mugs' }));
    return;
  }
  if (req.url.startsWith('/order/')) {
    try {
      const order = createOrder(req.url.split('/')[2], 1);
      res.writeHead(200, { 'content-type': 'application/json' });
      res.end(JSON.stringify(order));
    } catch (err) {
      res.writeHead(400, { 'content-type': 'application/json' });
      res.end(JSON.stringify({ error: err.message }));
    }
    return;
  }
  res.writeHead(404);
  res.end();
});

server.listen(port, '0.0.0.0', () => console.log(`listening on ${port}`));
