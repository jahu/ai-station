import { useMutation, useQueryClient } from "@tanstack/react-query";
import { uploadDataFiles } from "./data-upload";
import { uploadImageFiles } from "./image-upload";
import type { ConversationDataScope } from "./useDataInputs";

type Selection =
  | { kind: "data"; scope: ConversationDataScope }
  | { kind: "images"; ids: string[] };
export function useConversationAttachmentUpload(
  onSelected: (selection: Selection) => void,
) {
  const cache = useQueryClient();
  return useMutation({
    mutationFn: ({
      kind,
      files,
    }: {
      kind: "data" | "images";
      files: File[];
    }) =>
      kind === "data"
        ? uploadDataFiles(files, cache, (artifacts) =>
            onSelected({
              kind,
              scope: {
                input_artifact_ids: artifacts.map((artifact) => artifact.id),
                max_repairs: 1,
                model: "auto",
                maximum_runtime: 600,
              },
            }),
          )
        : uploadImageFiles(files, cache, (artifacts) =>
            onSelected({ kind, ids: artifacts.map((artifact) => artifact.id) }),
          ),
  });
}
