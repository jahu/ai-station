import { useEffect, useState } from "react";
import { useInfiniteQuery } from "@tanstack/react-query";
import { api, type Artifact } from "../../api";

// Search the stored collection, not just the first page already in the browser.
export function useLibraryAssets(
  kind: string,
  search: string,
  enabled: boolean,
) {
  const [term, setTerm] = useState("");
  useEffect(() => {
    const timer = setTimeout(() => setTerm(search.trim()), 200);
    return () => clearTimeout(timer);
  }, [search]);
  return useInfiniteQuery({
    queryKey: ["library", "inputs", kind, term],
    enabled,
    initialPageParam: 0,
    queryFn: ({ pageParam, signal }) =>
      api<Artifact[]>(
        `/artifacts?${new URLSearchParams({ kind, search: term, limit: "40", offset: String(pageParam) })}`,
        { signal },
      ),
    getNextPageParam: (last, pages) =>
      last.length === 40 ? pages.length * 40 : undefined,
  });
}
