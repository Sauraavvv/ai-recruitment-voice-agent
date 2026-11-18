"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError } from "./api";

type LoadState<T> = { key: string; data?: T; error?: ApiError };

/**
 * Load data for `key`; reloads when the key changes or `reload()` is called.
 * Keeps the previous data while a new load is in flight. `key = null` skips loading.
 */
export function useLoad<T>(key: string | null, loader: () => Promise<T>) {
  const loaderRef = useRef(loader);
  useEffect(() => {
    loaderRef.current = loader;
  });
  const [version, setVersion] = useState(0);
  const [state, setState] = useState<LoadState<T>>({ key: "" });
  const fullKey = key === null ? null : `${key}#${version}`;

  useEffect(() => {
    if (fullKey === null) return;
    let cancelled = false;
    loaderRef.current().then(
      (data) => !cancelled && setState({ key: fullKey, data }),
      (error: unknown) =>
        !cancelled &&
        setState((previous) => ({
          key: fullKey,
          data: previous.data,
          error: error instanceof ApiError ? error : new ApiError(0, "error", String(error)),
        })),
    );
    return () => {
      cancelled = true;
    };
  }, [fullKey]);

  const reload = useCallback(() => setVersion((v) => v + 1), []);
  return {
    data: state.data,
    error: state.key === fullKey ? state.error : undefined,
    loading: fullKey !== null && state.key !== fullKey,
    reload,
    setData: (data: T) => setState({ key: fullKey ?? "", data }),
  };
}
