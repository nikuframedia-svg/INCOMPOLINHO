import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { Modal } from "../src/components/ui/Modal";

afterEach(cleanup);

it("allows a long lot title to wrap without squeezing the close button", () => {
  const title = "Mover lote LOT_VUL192_PRM019_8750787433_25";
  render(<Modal title={title} onClose={() => {}}><p>Preview</p></Modal>);
  const heading = screen.getByText(title);
  const close = screen.getByRole("button", { name: `Fechar ${title}` });
  expect(heading.style.minWidth).toBe("0px");
  expect(heading.style.overflowWrap).toBe("anywhere");
  expect(close.style.flexShrink).toBe("0");
});
