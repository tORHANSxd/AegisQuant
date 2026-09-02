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

function safePreferences(value: string | null): Preferences {
  if (!value) return defaults;
  try {
    const parsed = JSON.parse(value) as Partial<Preferences>;
    return {
      theme: parsed.theme === "light" ? "light" : "dark",
      density: parsed.density === "compact" ? "compact" : "comfortable",
      marketColors: parsed.marketColors === "red-up" ? "red-up" : "green-up",
      highContrast: parsed.highContrast === true,
      colorBlind: parsed.colorBlind === true,
    };
  } catch {
    return defaults;
  }
}

function usePreferences() {
  const [preferences, setPreferences] = useState<Preferences>(defaults);
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    const frame = requestAnimationFrame(() => {
      setPreferences(safePreferences(window.localStorage.getItem(STORAGE_KEY)));
      setHydrated(true);
    });
    return () => cancelAnimationFrame(frame);
  }, []);

  useEffect(() => {
    if (!hydrated) return;
    const root = document.documentElement;
    root.dataset.theme = preferences.theme;
    root.dataset.density = preferences.density;
    root.dataset.marketColors = preferences.marketColors;
    root.dataset.contrast = preferences.highContrast ? "high" : "standard";
    root.dataset.colorBlind = preferences.colorBlind ? "on" : "off";
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(preferences));
  }, [hydrated, preferences]);

  const reset = () => setPreferences(defaults);
  return { preferences, setPreferences, reset };
}

function PreferenceEditor({ showReset = false }: Readonly<{ showReset?: boolean }>) {
  const { preferences, setPreferences, reset } = usePreferences();
  return (
    <div className="preference-editor">
      <label>
        主题
        <select
          value={preferences.theme}
          onChange={(event) => setPreferences((current) => ({ ...current, theme: event.target.value as Theme }))}
        >
          <option value="dark">深色</option>
          <option value="light">浅色</option>
        </select>
      </label>
      <label>
        密度
        <select
          value={preferences.density}
          onChange={(event) => setPreferences((current) => ({ ...current, density: event.target.value as Density }))}
        >
          <option value="comfortable">舒适</option>
          <option value="compact">紧凑</option>
        </select>
      </label>
      <label>
        涨跌色
        <select
          value={preferences.marketColors}
          onChange={(event) => setPreferences((current) => ({ ...current, marketColors: event.target.value as MarketColors }))}
        >
          <option value="green-up">绿涨红跌</option>
          <option value="red-up">红涨绿跌</option>
        </select>
      </label>
      <label className="toggle-row">
        <input
          type="checkbox"
          checked={preferences.highContrast}
          onChange={(event) => setPreferences((current) => ({ ...current, highContrast: event.target.checked }))}
        />
        高对比
      </label>
      <label className="toggle-row">
        <input
          type="checkbox"
          checked={preferences.colorBlind}
          onChange={(event) => setPreferences((current) => ({ ...current, colorBlind: event.target.checked }))}
        />
        色盲友好
      </label>
      {showReset ? <button type="button" className="secondary-button" onClick={reset}>恢复显示默认值</button> : null}
    </div>
  );
}

export function PreferenceControls() {
  return (
    <details className="preference-controls">
      <summary aria-label="显示偏好">显示</summary>
      <PreferenceEditor />
    </details>
  );
}

export function SettingsPanel() {
  return (
    <section className="settings-panel" aria-labelledby="display-settings-title">
      <div>
        <p className="section-kicker">LOCAL DISPLAY ONLY</p>
        <h2 id="display-settings-title">本机显示偏好</h2>
        <p>设置只保存在当前浏览器，不写入服务端，也不能改变风险限额、策略参数或交易权限。</p>
      </div>
      <PreferenceEditor showReset />
    </section>
  );
}
