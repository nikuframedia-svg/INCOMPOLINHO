import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { DataTable, type DataColumn } from "../src/components/ui/DataTable";
import { formatDuration } from "../src/lib/duration";

type Row = {
  id: string;
  machine: string;
  reference: string;
  quantity: number;
};

const rows: Row[] = [
  { id: "2", machine: "PRM042", reference: "BWI003", quantity: 80 },
  { id: "1", machine: "PRM019", reference: "VUL192", quantity: 120 },
];

const columns: DataColumn<Row>[] = [
  { id: "machine", label: "Máquina", value: (row) => row.machine },
  { id: "reference", label: "Referência", value: (row) => row.reference },
  { id: "quantity", label: "Quantidade", value: (row) => row.quantity },
];

afterEach(cleanup);

function renderTable() {
  return render(
    <DataTable
      rows={rows}
      columns={columns}
      rowKey={(row) => row.id}
      searchPlaceholder="Pesquisar produções"
      initialSort={{ id: "machine", direction: "asc" }}
    />,
  );
}

describe("DataTable", () => {
  it("pesquisa em todas as colunas e atualiza a contagem", () => {
    renderTable();

    fireEvent.change(screen.getByRole("searchbox", { name: "Pesquisar produções" }), {
      target: { value: "BWI003" },
    });

    expect(screen.getByText("BWI003")).toBeTruthy();
    expect(screen.queryByText("VUL192")).toBeNull();
    expect(screen.getByText("1 de 2")).toBeTruthy();
  });

  it("ordena ao selecionar o cabeçalho", () => {
    renderTable();

    const body = screen.getByRole("table").querySelector("tbody");
    expect(body).not.toBeNull();
    const firstBefore = within(body!).getAllByRole("row")[0];
    expect(within(firstBefore).getByText("PRM019")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: /Máquina/ }));

    const firstAfter = within(body!).getAllByRole("row")[0];
    expect(within(firstAfter).getByText("PRM042")).toBeTruthy();
  });

  it("explica quando a pesquisa não encontra resultados", () => {
    renderTable();

    fireEvent.change(screen.getByRole("searchbox", { name: "Pesquisar produções" }), {
      target: { value: "não existe" },
    });

    expect(screen.getByText("Sem resultados")).toBeTruthy();
    expect(screen.getByText("0 de 2")).toBeTruthy();
  });
});

describe("capacidade", () => {
  it("apresenta carga e capacidade no formato hh:mm", () => {
    expect(formatDuration(0)).toBe("00:00");
    expect(formatDuration(635)).toBe("10:35");
  });
});
