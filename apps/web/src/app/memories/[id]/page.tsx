import { MemoryDetailPage } from "@/features/memory-explorer/MemoryDetailPage";

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <MemoryDetailPage memoryId={id} />;
}
