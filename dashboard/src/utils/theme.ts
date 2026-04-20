const THEMES = [
  { id: "purple-dark", name: "Purple Dark" },
  { id: "purple-light", name: "Purple Light" },
  { id: "dark", name: "Dark" },
  { id: "pride-dark", name: "Pride Dark" },
  { id: "pride-light", name: "Pride Light" },
  { id: "progress-pride-dark", name: "Progress Pride Dark" },
  { id: "progress-pride-light", name: "Progress Pride Light" },
  { id: "trans-pride-dark", name: "Trans Pride Dark" },
  { id: "trans-pride-light", name: "Trans Pride Light" },
  { id: "hot-dog-stand", name: "Hot Dog Stand" },
  { id: "arctic-reflection", name: "Arctic Reflection" },
  { id: "amber-walnut-morning", name: "Amber Walnut Morning" },
  { id: "pearl", name: "Pearl" },
  { id: "jade-pebble-morning", name: "Jade Pebble Morning" },
];

export function getTheme(): string {
  return localStorage.getItem("theme") || "purple-dark";
}

export function setTheme(id: string) {
  localStorage.setItem("theme", id);
  document.documentElement.setAttribute("data-theme", id);
}

export function initTheme() {
  setTheme(getTheme());
}

export { THEMES };
