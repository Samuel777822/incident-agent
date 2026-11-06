// Small helpers shared by every page.
function $(selector, root = document) {
  return root.querySelector(selector);
}

function $all(selector, root = document) {
  return Array.from(root.querySelectorAll(selector));
}

function highlightNav() {
  const here = location.pathname.split('/').pop() || 'index.html';
  $all('nav a').forEach((link) => {
    if (link.getAttribute('href') === here) {
      link.classList.add('current');
    }
  });
}

function wireForms() {
  $all('form').forEach((form) => {
    form.addEventListener('submit', (event) => {
      const email = form.querySelector('input[type=email]');
      if (email && !email.value.includes('@')) {
        event.preventDefault();
        alert('Please enter a valid email address');
      }
    });
  });
}

window.addEventListener('DOMContentLoaded', () => {
  highlightNav();
  wireForms();
});
