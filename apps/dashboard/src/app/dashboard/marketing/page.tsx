'use client';

import { DraftsPanel } from '@/components/ops/drafts';
import { WorkspacePage } from '@/components/ops/workspace';

export default function MarketingPage() {
  return (
    <WorkspacePage title="Marketing" subtitle="Campaigns, launch copy, emails, posts and press, written from the product's real features and changes">
      {(workspaceId) => (
        <div className="space-y-6">
          <DraftsPanel key={workspaceId} workspaceId={workspaceId} group="marketing" title="Marketing drafts"
            hint="Every draft is grounded in this workspace's README, code, commits and records. Publishing or emailing from your accounts stays with you." />
        </div>
      )}
    </WorkspacePage>
  );
}
