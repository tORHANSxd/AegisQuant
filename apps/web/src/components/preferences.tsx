"use client";

import { useEffect, useState } from "react";

type Theme = "dark" | "light";
type Density = "comfortable" | "compact";
type MarketColors = "green-up" | "red-up";

const STORAGE_KEY = "aegisquant-ui-preferences-v1";

interface Preferences {
  theme: Theme;
  density: Density;
  marketColors: MarketColors;
  highContrast: boolean;
  colorBlind: boolean;
}

const defaults: Preferences = {
  theme: "dark",
  density: "comfortable",
  marketColors: "green-up",
  highContrast: false,
  colorBlind: false,
};

export function PreferenceControls() {
  const [preferences, setPreferences] = useState<Preferences>(defaults);
  useEffect(() => {
    const frame = requestAnimationFrame(() => {
      const saved = window.localStorage.getItem(STORAGE_KEY);
      if (saved) {
        try {
          setPreferences({ ...defaults, ...(JSON.parse(saved) as Partial<Preferences>) });
        } catch {
          window.localStorage.removeItem(STORAGE_KEY);
        }
      }
    });
    return () => cancelAnimationFrame(frame);
  }, []);
  useEffect(() => {
    const root = document.documentElement;
    root.dataset.theme = preferences.theme;
    root.dataset.density = preferences.density;
    root.dataset.marketColors = preferences.marketColors;
    root.dataset.contrast = preferences.highContrast ? "high" : "standard";
    root.dataset.colorBlind = preferences.colorBlind ? "on" : "off";
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(preferences));
  }, [preferences]);
  return (
    <details className="preference-controls">
      <summary aria-label="显示偏好">显示</summary>
      <div>
        <label>主题<select value={preferences.theme} onChange={(event) => setPreferences((current) => ({ ...current, theme: event.target.value as Theme }))}><option value="dark">深色</option><option value="light">浅色</option></select></label>
        <label>密度<select value={preferences.density} onChange={(event) => setPreferences((current) => ({ ...current, density: event.target.value as Density }))}><option value="comfortable">舒适</option><option value="compact">紧凑</option></select></label>
        <label>涨跌色<select value={preferences.marketColors} onChange={(event) => setPreferences((current) => ({ ...current, marketColors: event.target.value as MarketColors }))}><option value="green-up">绿涨红跌</option><option value="red-up">红涨绿跌</option></select></label>
        <label><input type="checkbox" checked={preferences.highContrast} onChange={(event) => setPreferences((current) => ({ ...current, highContrast: event.target.checked }))} />高对比</label>
        <label><input type="checkbox" checked={preferences.colorBlind} onChange={(event) => setPreferences((current) => ({ ...current, colorBlind: event.target.checked }))} />色盲友好</label>
      </div>
    </details>
  );
}
