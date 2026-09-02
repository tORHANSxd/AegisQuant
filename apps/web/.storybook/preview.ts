import type { Preview } from "@storybook/react-webpack5";

import "../app/globals.css";

const preview: Preview = {
  parameters: {
    a11y: { test: "error" },
    controls: { expanded: true },
  },
};

export default preview;
