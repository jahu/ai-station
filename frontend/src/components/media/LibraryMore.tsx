import { useEffect, useRef } from "react";
import { Button } from "../ui/button";

export default function LibraryMore({
  hasNextPage,
  isFetchingNextPage,
  isFetchNextPageError,
  fetchNextPage,
}: {
  hasNextPage: boolean;
  isFetchingNextPage: boolean;
  isFetchNextPageError: boolean;
  fetchNextPage: () => unknown;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (
      !ref.current ||
      !hasNextPage ||
      isFetchingNextPage ||
      isFetchNextPageError ||
      typeof IntersectionObserver === "undefined"
    )
      return;
    const observer = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting) void fetchNextPage();
    });
    observer.observe(ref.current);
    return () => observer.disconnect();
  }, [hasNextPage, isFetchingNextPage, isFetchNextPageError, fetchNextPage]);
  if (!hasNextPage) return null;
  return (
    <div ref={ref} className="library-more">
      <Button
        type="button"
        variant="ghost"
        disabled={isFetchingNextPage}
        onClick={() => void fetchNextPage()}
      >
        {isFetchingNextPage
          ? "Loading…"
          : isFetchNextPageError
            ? "Retry loading more files"
            : "Load more files"}
      </Button>
    </div>
  );
}
