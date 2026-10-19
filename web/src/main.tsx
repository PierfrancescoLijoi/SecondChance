import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { App } from "./App";
import { loadConfig } from "./config";
import "./styles.css";

const root = createRoot(document.getElementById("root") as HTMLElement);

loadConfig()
  .then(() =>
    root.render(
      <StrictMode>
        <BrowserRouter>
          <App />
        </BrowserRouter>
      </StrictMode>,
    ),
  )
  .catch(() => root.render(<p role="alert">Configuration not available: please try again later.</p>));
