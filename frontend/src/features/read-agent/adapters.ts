import type {
  EditorOperation,
  ProjectRecord,
  SemanticViewModel,
  SemanticViewObject,
} from "./types";

export function allFloors(project: ProjectRecord | null) {
  return (
    project?.buildings.flatMap((building) =>
      building.floors.map((floor) => ({
        ...floor,
        building_id: building.building_id,
        building_name: building.building_name,
      })),
    ) ?? []
  );
}

export function projectToSummary(project: ProjectRecord) {
  const floors = allFloors(project);
  return {
    project_id: project.project_id,
    name: project.name,
    discipline: project.discipline,
    floor_ids: floors.map((floor) => floor.floor_id),
    blueprint_ids: floors.flatMap((floor) =>
      floor.blueprints.map((blueprint) => blueprint.blueprint_id),
    ),
    updated_at: project.updated_at,
  };
}

export function objectsForLayer(
  viewModel: SemanticViewModel | null,
  layer: string,
): SemanticViewObject[] {
  return viewModel?.objects.filter((object) => object.layer === layer) ?? [];
}

export function findObject(
  viewModel: SemanticViewModel | null,
  objectId: string | null,
): SemanticViewObject | null {
  if (!viewModel || !objectId) return null;
  return (
    viewModel.objects.find(
      (object) => object.semantic_object_id === objectId,
    ) ?? null
  );
}

export function formatSection(section: SemanticViewObject["section"]): string {
  if (!section) return "";
  if (typeof section === "string") return section.replace("x", "×");
  const width = section.width_mm;
  const height = section.height_mm;
  return width && height ? `${width}×${height}` : "";
}

export function parseSectionText(
  text: string,
): { width_mm: number; height_mm: number } | null {
  const match = /(\d{2,5})\s*[xX×]\s*(\d{2,5})/.exec(text.trim());
  if (!match) return null;
  return { width_mm: Number(match[1]), height_mm: Number(match[2]) };
}

export function createUpdateOperation(input: {
  object: SemanticViewObject;
  sectionText?: string;
  label?: string;
  reviewStatus?: string;
}): EditorOperation | null {
  if (input.object.object_type === "main_beam" && input.sectionText) {
    const section = parseSectionText(input.sectionText);
    if (!section) return null;
    return {
      operation_id: `op_${Date.now()}`,
      operation_type: "update_beam_section",
      actor: { type: "human", id: "web-ui-user" },
      target: {
        object_id: input.object.semantic_object_id,
        object_type: input.object.object_type,
      },
      params: {
        section,
        review_status: input.reviewStatus ?? "human_confirmed",
      },
    };
  }
  if (input.object.object_type === "column" && input.sectionText) {
    const section = parseSectionText(input.sectionText);
    if (!section) return null;
    return {
      operation_id: `op_${Date.now()}`,
      operation_type: "update_column_section",
      actor: { type: "human", id: "web-ui-user" },
      target: {
        object_id: input.object.semantic_object_id,
        object_type: input.object.object_type,
      },
      params: {
        section,
        review_status: input.reviewStatus ?? "human_confirmed",
      },
    };
  }
  if (input.reviewStatus) {
    return {
      operation_id: `op_${Date.now()}`,
      operation_type: "update_review_status",
      actor: { type: "human", id: "web-ui-user" },
      target: {
        object_id: input.object.semantic_object_id,
        object_type: input.object.object_type,
      },
      params: { review_status: input.reviewStatus },
    };
  }
  if (input.object.object_type === "main_beam" && input.label) {
    return {
      operation_id: `op_${Date.now()}`,
      operation_type: "update_beam_label",
      actor: { type: "human", id: "web-ui-user" },
      target: {
        object_id: input.object.semantic_object_id,
        object_type: input.object.object_type,
      },
      params: { label: input.label },
    };
  }
  return null;
}

export function viewBoxFor(viewModel: SemanticViewModel | null): string {
  const width = Math.max(
    Number(viewModel?.coordinate_system?.total_width_mm ?? 50000),
    1000,
  );
  const height = Math.max(
    Number(viewModel?.coordinate_system?.total_height_mm ?? 42000),
    1000,
  );
  return `${-2500} ${-2500} ${width + 5000} ${height + 5000}`;
}
