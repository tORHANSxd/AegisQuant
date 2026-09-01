import type { Preview } from "@storybook/nextjs";

import "../app/globals.css";

const preview: Preview = {
  parameters: {
    a11y: { test: "error" },
    controls: { expanded: true },
  },
};

export default preview;
