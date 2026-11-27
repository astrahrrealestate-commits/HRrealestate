"use client";

import { Dispatch, SetStateAction, useCallback, useRef, useState } from "react";
import { readView, updateView } from "@/lib/viewCache";

/**
 * `useState` for data a page loaded from the API: it starts from what the page showed last time. The page still
 * fetches on mount and overwrites it. `key` must be constant for the life of the component.
 *
 * The setter writes the cache itself rather than from an effect: a rollback or a late answer that arrives after the
 * page has gone is still recorded, so the next visit does not show the optimistic value as done.
 */
export function useCachedState<T>(key: string, initial: T): [T, Dispatch<SetStateAction<T>>] {
  const initialRef = useRef(initial);
  const [value, setValue] = useState<T>(() => {
    const cached = readView<T>(key);
    return cached === undefined ? initial : cached;
  });
  const set = useCallback<Dispatch<SetStateAction<T>>>(
    (action) => setValue(updateView<T>(key, action, initialRef.current)),
    [key]
  );
  return [value, set];
}
