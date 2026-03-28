// Fade-in on scroll
document.addEventListener('DOMContentLoaded', () => {
  const targets = document.querySelectorAll('.feature-card, .screenshot-card, .step, .standings-img-wrap');
  const observer = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          entry.target.classList.add('visible');
          observer.unobserve(entry.target);
        }
      });
    },
    { threshold: 0.15 }
  );
  targets.forEach((el) => observer.observe(el));

  // Standings image rotation
  const standingsImg = document.getElementById('standings-rotating-img');
  if (standingsImg) {
    const images = ['standings.png', 'standings2.png'];
    let idx = 0;
    setInterval(() => {
      idx = (idx + 1) % images.length;
      standingsImg.src = images[idx];
    }, 5000);
  }
});
