import type { Meta, StoryObj } from "@storybook/nextjs";

import { ComponentGallery } from "./component-gallery";

const meta = {
  title: "AegisQuant/Complete State Gallery",
  component: ComponentGallery,
  parameters: { layout: "fullscreen" },
  tags: ["autodocs"],
} satisfies Meta<typeof ComponentGallery>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Normal: Story = { args: { state: "LIVE" } };
export const Loading: Story = { args: { state: "LOADING" } };
export const Empty: Story = { args: { state: "EMPTY" } };
export const Stale: Story = { args: { state: "STALE" } };
export const Degraded: Story = { args: { state: "DEGRADED" } };
export const Disconnected: Story = { args: { state: "DISCONNECTED" } };
export const Error: Story = { args: { state: "ERROR" } };
export const PermissionDenied: Story = { args: { state: "PERMISSION_DENIED" } };
export const Narrow: Story = {
  args: { state: "LIVE" },
  decorators: [(Story) => <div className="story-narrow"><Story /></div>],
};
export const Accessible: Story = {
  args: { state: "STALE" },
  parameters: { a11y: { test: "error" } },
};
