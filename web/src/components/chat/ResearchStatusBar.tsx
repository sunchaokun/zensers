'use client';

import { Loader2, Brain, ChevronDown, ChevronUp } from 'lucide-react';
import { useResearchStore } from '@/store/useResearchStore';
import { Progress } from '@/components/ui/progress';
import { useState } from 'react';

export function ResearchStatusBar() {
  const status = useResearchStore((s) => s.status);
  const progress = useResearchStore((s) => s.progress);
  const phases = useResearchStore((s) => s.phases);
  const framework = useResearchStore((s) => s.framework);
  const [expanded, setExpanded] = useState(false);

  if (status !== 'running' && status !== 'paused') return null;

  const currentPhase = phases.find(p => p.status === 'running');
  const completedCount = phases.filter(p => p.status === 'completed').length;
  const hasProgress = currentPhase || progress > 0 || completedCount > 0;
  const hasFramework = framework && framework.sections && framework.sections.length > 0;

  if (!hasProgress && !hasFramework) return null;

  return (
    <div className="bg-background/95 backdrop-blur border-b px-4 py-2">
      <div className="flex items-center gap-3">
        {status === 'paused' ? (
          <Loader2 className="h-4 w-4 text-amber-500" />
        ) : (
          <Loader2 className="h-4 w-4 animate-spin text-blue-500" />
        )}
        <span className="text-sm font-medium truncate">
          {status === 'paused'
            ? (framework?.topic ? `已暂停: ${framework.topic}` : '研究已暂停')
            : hasProgress
              ? (currentPhase?.name || (completedCount > 0 ? 'Generating analysis...' : 'Preparing...'))
              : (framework?.topic || 'Researching...')}
        </span>
        {hasProgress && (
          <span className="text-xs text-muted-foreground ml-auto shrink-0">
            {completedCount}/{phases.length} phases
          </span>
        )}
        {hasFramework && (
          <button
            onClick={() => setExpanded(!expanded)}
            className="shrink-0 p-0.5 rounded hover:bg-muted/50 transition-colors"
          >
            {expanded ? <ChevronUp className="h-3.5 w-3.5 text-muted-foreground" /> : <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />}
          </button>
        )}
      </div>
      {hasProgress && <Progress value={progress * 100} className="h-1 mt-1" />}
      {expanded && hasFramework && (
        <div className="mt-1.5 pt-1.5 border-t border-border/30">
          <div className="flex items-center gap-1.5 mb-1">
            <Brain className="h-3.5 w-3.5 text-purple-600" />
            <span className="text-xs text-muted-foreground">
              {(/[\u4e00-\u9fff]/.test(framework.topic || '') ? '研究框架' : 'Framework')}: {framework.topic}
            </span>
          </div>
          <div className="flex flex-wrap gap-1">
            {framework.sections.slice(0, 8).map((s, i) => (
              <span key={i} className="inline-flex items-center px-1.5 py-0.5 rounded bg-primary/10 text-[10px] text-primary">
                {s}
              </span>
            ))}
            {framework.sections.length > 8 && (
              <span className="text-[10px] text-muted-foreground">+{framework.sections.length - 8}</span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
