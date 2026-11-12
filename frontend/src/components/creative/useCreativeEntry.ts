import { useLayoutEffect } from "react";

export function useCreativeEntry(identity?: string) {
  useLayoutEffect(() => {
    const main = document.getElementById("main");
    if (main) main.scrollTop = 0;
    document.documentElement.scrollTop = 0;
  }, [identity]);
}
