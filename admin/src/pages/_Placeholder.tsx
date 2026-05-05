import { Construction } from 'lucide-react';

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';

export interface PlaceholderProps {
  title: string;
  description?: string;
}

/**
 * Shared "Coming soon" placeholder used by routes that the parallel SPA agent
 * is responsible for filling in. Once those pages exist, simply replace the
 * import in `App.tsx`.
 */
export default function Placeholder({ title, description }: PlaceholderProps) {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">{title}</h1>
        {description && (
          <p className="mt-1 text-sm text-muted-foreground">{description}</p>
        )}
      </div>
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Construction className="h-4 w-4" />
            Coming soon
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">
            Эта страница в работе. Сценарий доделает параллельный агент.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
