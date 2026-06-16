import ReactDOM from "react-dom/client";
import { App } from "./App";
import "./index.css";

// Hydrate persisted dark mode before first paint to avoid flash
if (
  localStorage.getItem("theme") === "dark" ||
  (!localStorage.getItem("theme") && window.matchMedia("(prefers-color-scheme: dark)").matches)
) {
  document.documentElement.classList.add("dark");
}

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <App />,
);
