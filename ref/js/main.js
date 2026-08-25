document.addEventListener("DOMContentLoaded", () => {
  const data = window.DIGIGARMENT_DATA;

  const newsList = document.getElementById("newsList");
  data.news.forEach(item => {
    newsList.insertAdjacentHTML("beforeend", `
      <div class="news-item">
        <div class="news-thumb"></div>
        <div><b>${item.title}</b><small>${item.date}</small></div>
      </div>`);
  });

  const yarnTable = document.getElementById("yarnTable");
  data.yarn.forEach(item => {
    yarnTable.insertAdjacentHTML("beforeend", `
      <tr>
        <td>${item.count}</td><td>${item.type}</td><td>₹${item.price.toFixed(2)}</td>
        <td class="${item.dir}">${item.dir === "up" ? "▲" : "▼"} ${item.trend}</td>
        <td>Today</td>
      </tr>`);
  });

  const serviceList = document.getElementById("serviceList");
  data.services.forEach(item => {
    serviceList.insertAdjacentHTML("beforeend", `
      <div class="service"><b>${item[0]}</b><small>${item[1]}</small></div>`);
  });

  const toggle = document.querySelector(".menu-toggle");
  const nav = document.getElementById("mainNav");
  toggle.addEventListener("click", () => {
    const open = nav.classList.toggle("open");
    toggle.setAttribute("aria-expanded", String(open));
  });

  nav.querySelectorAll("a").forEach(link => {
    link.addEventListener("click", () => nav.classList.remove("open"));
  });

  document.querySelector(".newsletter")?.addEventListener("submit", e => {
    e.preventDefault();
    alert("Newsletter signup will be connected to the CMS later.");
  });
});