import { ObservatoryProposalPage } from "@/features/observatory/ObservatoryProposalPage";

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <ObservatoryProposalPage proposalId={id} />;
}
