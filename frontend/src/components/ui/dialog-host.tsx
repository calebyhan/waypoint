"use client";

import * as React from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

type ConfirmOptions = {
  title: string;
  description?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  destructive?: boolean;
};

type PromptOptions = {
  title: string;
  description?: string;
  defaultValue?: string;
  placeholder?: string;
  confirmLabel?: string;
  cancelLabel?: string;
};

type LinkOptions = {
  title: string;
  description?: string;
  value: string;
  closeLabel?: string;
};

type DialogState =
  | { kind: "confirm"; options: ConfirmOptions; resolve: (value: boolean) => void }
  | { kind: "prompt"; options: PromptOptions; resolve: (value: string | null) => void }
  | { kind: "link"; options: LinkOptions; resolve: () => void }
  | null;

let setState: ((state: DialogState) => void) | null = null;

/** Custom replacement for window.confirm — resolves true/false instead of blocking the thread. */
export function confirmDialog(options: ConfirmOptions): Promise<boolean> {
  return new Promise((resolve) => {
    setState?.({ kind: "confirm", options, resolve });
  });
}

/** Custom replacement for window.prompt — resolves the entered text, or null if cancelled. */
export function promptDialog(options: PromptOptions): Promise<string | null> {
  return new Promise((resolve) => {
    setState?.({ kind: "prompt", options, resolve });
  });
}

/** Shows read-only text (e.g. a link) for manual copying when the Clipboard API is unavailable. */
export function linkDialog(options: LinkOptions): Promise<void> {
  return new Promise((resolve) => {
    setState?.({ kind: "link", options, resolve });
  });
}

/** Mounted once in the root layout; renders whichever imperative dialog is currently active. */
export function DialogHost() {
  const [state, internalSetState] = React.useState<DialogState>(null);
  const inputRef = React.useRef<HTMLInputElement>(null);

  React.useEffect(() => {
    setState = internalSetState;
    return () => {
      setState = null;
    };
  }, []);

  if (!state) return null;

  if (state.kind === "confirm") {
    const { options, resolve } = state;
    return (
      <Dialog
        open
        onOpenChange={(open) => {
          if (!open) {
            resolve(false);
            internalSetState(null);
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{options.title}</DialogTitle>
            {options.description && (
              <DialogDescription>{options.description}</DialogDescription>
            )}
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => {
                resolve(false);
                internalSetState(null);
              }}
            >
              {options.cancelLabel ?? "Cancel"}
            </Button>
            <Button
              variant={options.destructive ? "destructive" : "default"}
              onClick={() => {
                resolve(true);
                internalSetState(null);
              }}
            >
              {options.confirmLabel ?? "Confirm"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    );
  }

  if (state.kind === "prompt") {
    const { options, resolve } = state;
    const submit = () => {
      resolve(inputRef.current?.value.trim() || null);
      internalSetState(null);
    };
    const cancel = () => {
      resolve(null);
      internalSetState(null);
    };
    return (
      <Dialog
        open
        onOpenChange={(open) => {
          if (!open) cancel();
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{options.title}</DialogTitle>
            {options.description && (
              <DialogDescription>{options.description}</DialogDescription>
            )}
          </DialogHeader>
          <Input
            ref={inputRef}
            autoFocus
            defaultValue={options.defaultValue}
            placeholder={options.placeholder}
            onKeyDown={(e) => {
              if (e.key === "Enter") submit();
            }}
          />
          <DialogFooter>
            <Button variant="outline" onClick={cancel}>
              {options.cancelLabel ?? "Cancel"}
            </Button>
            <Button onClick={submit}>{options.confirmLabel ?? "Save"}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    );
  }

  const { options, resolve } = state;
  const close = () => {
    resolve();
    internalSetState(null);
  };
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) close();
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{options.title}</DialogTitle>
          {options.description && (
            <DialogDescription>{options.description}</DialogDescription>
          )}
        </DialogHeader>
        <Input
          autoFocus
          readOnly
          value={options.value}
          onFocus={(e) => e.currentTarget.select()}
        />
        <DialogFooter>
          <Button onClick={close}>{options.closeLabel ?? "Done"}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
