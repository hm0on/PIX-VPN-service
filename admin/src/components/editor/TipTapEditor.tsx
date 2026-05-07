import { useEffect } from 'react';
import { useEditor, EditorContent, type Editor } from '@tiptap/react';
import { Mark, mergeAttributes } from '@tiptap/core';
import StarterKit from '@tiptap/starter-kit';
import Link from '@tiptap/extension-link';

// Custom mark for Telegram's spoiler.
//
// StarterKit doesn't ship a span/spoiler mark, and ProseMirror will silently
// drop any markup it doesn't have a schema entry for — so plain
// ``insertContent('<span class="tg-spoiler">...</span>')`` would parse the
// span away the moment the editor re-serialised the doc, leaving the user's
// "spoilered" text bare HTML in the saved DB row.
//
// Defining this mark as a real schema node makes the round-trip lossless:
// ``parseHTML`` recognises ``<span class="tg-spoiler">`` on load, and
// ``renderHTML`` emits the same markup on every ``getHTML()`` call so the
// bot's ``_normalize_message_html`` regex can convert it to a real
// ``<tg-spoiler>`` Telegram tag.
const SpoilerMark = Mark.create({
  name: 'tgSpoiler',
  inclusive: true,
  parseHTML() {
    return [
      {
        tag: 'span.tg-spoiler',
      },
      {
        tag: 'tg-spoiler',
      },
    ];
  },
  renderHTML({ HTMLAttributes }) {
    return ['span', mergeAttributes(HTMLAttributes, { class: 'tg-spoiler' }), 0];
  },
  addCommands() {
    return {
      toggleSpoiler:
        () =>
        ({ commands }) =>
          commands.toggleMark(this.name),
      setSpoiler:
        () =>
        ({ commands }) =>
          commands.setMark(this.name),
      unsetSpoiler:
        () =>
        ({ commands }) =>
          commands.unsetMark(this.name),
    };
  },
});
import {
  Bold,
  Italic,
  Link as LinkIcon,
  EyeOff,
  Smile,
  List,
  ListOrdered,
  Heading2,
  Heading3,
} from 'lucide-react';

import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

interface ToolbarProps {
  editor: Editor;
  disabled?: boolean;
}

function Toolbar({ editor, disabled }: ToolbarProps) {
  const insertSpoiler = () => {
    // Toggle the ``tgSpoiler`` mark on the current selection. Using the mark
    // (instead of raw insertContent) keeps the markup round-trippable: the
    // ProseMirror schema knows about ``span.tg-spoiler`` so it survives every
    // ``getHTML()`` -> save -> reload cycle. Toggling on an empty selection
    // arms the mark for the next typed character — same UX as bold/italic.
    editor.chain().focus().toggleMark('tgSpoiler').run();
  };

  const insertEmoji = () => {
    const id = window.prompt('emoji_id (custom Telegram emoji id)');
    if (!id) return;
    const fallback = window.prompt('Fallback (видимый, например ⭐)', '⭐') ?? '⭐';
    editor
      .chain()
      .focus()
      .insertContent(
        `<tg-emoji emoji-id="${escapeAttr(id)}">${escapeHtml(fallback)}</tg-emoji>`
      )
      .run();
  };

  const setLink = () => {
    const previous = editor.getAttributes('link').href as string | undefined;
    const url = window.prompt('URL', previous ?? 'https://');
    if (url === null) return;
    if (url === '') {
      editor.chain().focus().extendMarkRange('link').unsetLink().run();
      return;
    }
    editor.chain().focus().extendMarkRange('link').setLink({ href: url }).run();
  };

  const btn = (active: boolean) =>
    cn('h-8 w-8 p-0', active ? 'bg-accent text-accent-foreground' : '');

  return (
    <div className="flex flex-wrap items-center gap-1 border-b border-border bg-card px-2 py-1">
      <Button
        type="button"
        size="sm"
        variant="ghost"
        className={btn(editor.isActive('bold'))}
        disabled={disabled}
        onClick={() => editor.chain().focus().toggleBold().run()}
        title="Жирный"
      >
        <Bold className="h-4 w-4" />
      </Button>
      <Button
        type="button"
        size="sm"
        variant="ghost"
        className={btn(editor.isActive('italic'))}
        disabled={disabled}
        onClick={() => editor.chain().focus().toggleItalic().run()}
        title="Курсив"
      >
        <Italic className="h-4 w-4" />
      </Button>
      <Button
        type="button"
        size="sm"
        variant="ghost"
        className={btn(editor.isActive('heading', { level: 2 }))}
        disabled={disabled}
        onClick={() => editor.chain().focus().toggleHeading({ level: 2 }).run()}
        title="Заголовок 2"
      >
        <Heading2 className="h-4 w-4" />
      </Button>
      <Button
        type="button"
        size="sm"
        variant="ghost"
        className={btn(editor.isActive('heading', { level: 3 }))}
        disabled={disabled}
        onClick={() => editor.chain().focus().toggleHeading({ level: 3 }).run()}
        title="Заголовок 3"
      >
        <Heading3 className="h-4 w-4" />
      </Button>
      <Button
        type="button"
        size="sm"
        variant="ghost"
        className={btn(editor.isActive('bulletList'))}
        disabled={disabled}
        onClick={() => editor.chain().focus().toggleBulletList().run()}
        title="Список"
      >
        <List className="h-4 w-4" />
      </Button>
      <Button
        type="button"
        size="sm"
        variant="ghost"
        className={btn(editor.isActive('orderedList'))}
        disabled={disabled}
        onClick={() => editor.chain().focus().toggleOrderedList().run()}
        title="Нумерованный список"
      >
        <ListOrdered className="h-4 w-4" />
      </Button>
      <Button
        type="button"
        size="sm"
        variant="ghost"
        className={btn(editor.isActive('link'))}
        disabled={disabled}
        onClick={setLink}
        title="Ссылка"
      >
        <LinkIcon className="h-4 w-4" />
      </Button>
      <Button
        type="button"
        size="sm"
        variant="ghost"
        className={btn(editor.isActive('tgSpoiler'))}
        disabled={disabled}
        onClick={insertSpoiler}
        title="Спойлер"
      >
        <EyeOff className="h-4 w-4" />
      </Button>
      <Button
        type="button"
        size="sm"
        variant="ghost"
        className="h-8 w-8 p-0"
        disabled={disabled}
        onClick={insertEmoji}
        title="tg-emoji"
      >
        <Smile className="h-4 w-4" />
      </Button>
    </div>
  );
}

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

function escapeAttr(s: string): string {
  return s.replace(/"/g, '&quot;').replace(/&/g, '&amp;');
}

export interface TipTapEditorProps {
  value: string;
  onChange: (html: string) => void;
  disabled?: boolean;
  placeholder?: string;
  className?: string;
  minHeight?: string;
}

export function TipTapEditor({
  value,
  onChange,
  disabled,
  className,
  minHeight = '160px',
}: TipTapEditorProps) {
  const editor = useEditor({
    extensions: [
      StarterKit.configure({
        heading: { levels: [2, 3] },
      }),
      Link.configure({
        openOnClick: false,
        autolink: true,
        HTMLAttributes: { class: 'text-primary underline' },
      }),
      SpoilerMark,
    ],
    content: value || '<p></p>',
    editable: !disabled,
    onUpdate: ({ editor: ed }) => {
      onChange(ed.getHTML());
    },
  });

  useEffect(() => {
    if (!editor) return;
    if (editor.getHTML() !== value) {
      editor.commands.setContent(value || '<p></p>', false);
    }
  }, [value, editor]);

  useEffect(() => {
    if (editor) editor.setEditable(!disabled);
  }, [editor, disabled]);

  if (!editor) {
    return (
      <div
        className={cn(
          'rounded-md border border-input bg-background p-3 text-sm text-muted-foreground',
          className
        )}
        style={{ minHeight }}
      >
        Загрузка редактора…
      </div>
    );
  }

  return (
    <div className={cn('overflow-hidden rounded-md border border-input bg-background', className)}>
      <Toolbar editor={editor} disabled={disabled} />
      <EditorContent
        editor={editor}
        className="prose prose-sm max-w-none px-3 py-2 dark:prose-invert focus:outline-none [&_.ProseMirror]:outline-none [&_.ProseMirror]:min-h-[var(--editor-min-h)]"
        style={{ ['--editor-min-h' as string]: minHeight }}
      />
    </div>
  );
}
