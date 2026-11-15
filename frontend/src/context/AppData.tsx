import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { ApiError, getConfig, getHealth, getResults, getVersion } from "../lib/api";
import type { AppConfig, HealthData, Results, VersionData } from "../lib/types";

interface AppDataValue {
  results: Results | null;
  config: AppConfig | null;
  version: VersionData | null;
  health: HealthData | null;
  loading: boolean;
  error: string | null;
  apiOnline: boolean;
  lastChecked: Date | null;
  reload: () => void;
}

const AppDataContext = createContext<AppDataValue | null>(null);

export function AppDataProvider({ children }: { children: ReactNode }) {
  const [results, setResults] = useState<Results | null>(null);
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [version, setVersion] = useState<VersionData | null>(null);
  const [health, setHealth] = useState<HealthData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [apiOnline, setApiOnline] = useState(false);
  const [lastChecked, setLastChecked] = useState<Date | null>(null);
  const generation = useRef(0);

  const load = useCallback(async () => {
    const current = ++generation.current;
    setLoading(true);
    setError(null);

    const [resultsResult, configResult, versionResult, healthResult] = await Promise.allSettled([
      getResults(),
      getConfig(),
      getVersion(),
      getHealth(),
    ]);

    if (current !== generation.current) return;

    if (resultsResult.status === "fulfilled") setResults(resultsResult.value);
    if (configResult.status === "fulfilled") setConfig(configResult.value);
    if (versionResult.status === "fulfilled") setVersion(versionResult.value);
    if (healthResult.status === "fulfilled") setHealth(healthResult.value);

    const online = healthResult.status === "fulfilled" && healthResult.value.status === "ok";
    setApiOnline(online);
    setLastChecked(new Date());

    if (resultsResult.status === "rejected") {
      const reason = resultsResult.reason;
      setError(
        reason instanceof ApiError
          ? reason.message
          : "The verified results payload could not be loaded.",
      );
    } else if (configResult.status === "rejected") {
      const reason = configResult.reason;
      setError(
        reason instanceof ApiError
          ? `Configuration unavailable: ${reason.message}`
          : "The serving configuration could not be loaded.",
      );
    }

    setLoading(false);
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const value = useMemo<AppDataValue>(
    () => ({
      results,
      config,
      version,
      health,
      loading,
      error,
      apiOnline,
      lastChecked,
      reload: () => {
        void load();
      },
    }),
    [results, config, version, health, loading, error, apiOnline, lastChecked, load],
  );

  return <AppDataContext.Provider value={value}>{children}</AppDataContext.Provider>;
}

export function useAppData(): AppDataValue {
  const value = useContext(AppDataContext);
  if (!value) throw new Error("useAppData must be used inside AppDataProvider");
  return value;
}
