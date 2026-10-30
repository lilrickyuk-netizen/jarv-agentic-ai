'use client';

import { DraftsPanel } from '@/components/ops/drafts';
import { WorkspacePage } from '@/components/ops/workspace';

export default function ContentPage() {
  return (
    <WorkspacePage title="Content" subtitle="Technical posts, tutorials, changelogs, release notes, guides and help articles from the code itself">
      {(workspaceId) => (
        <div className="space-y-6">
          <DraftsPanel key={workspaceId} workspaceId={workspaceId} group="content" title="Content drafts"
            hint="Changelogs and release notes come from the git history; API examples from the routes in the code. Gaps are marked to confirm." />
        </div>
      )}
    </WorkspacePage>
  );
}
