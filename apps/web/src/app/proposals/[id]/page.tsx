import { ProposalDetailPage } from "@/features/proposals/ProposalDetailPage";

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <ProposalDetailPage proposalId={id} />;
}
