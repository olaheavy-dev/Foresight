import { render, screen } from "@testing-library/react";
import { ShippingStatus } from "./ShippingStatus";

const features = [
  { key: "forecast", stage: 1, title: "Cash-flow forecast", enabled: true },
  { key: "ask", stage: 2, title: "Ask", enabled: false },
];

describe("ShippingStatus", () => {
  it("lists shipped and planned features separately", () => {
    render(<ShippingStatus features={features} />);
    const shipped = screen.getByRole("region", { name: "Shipped" });
    const planned = screen.getByRole("region", { name: "Not shipped yet" });
    expect(shipped).toHaveTextContent("Cash-flow forecast");
    expect(shipped).not.toHaveTextContent("Ask");
    expect(planned).toHaveTextContent("Stage 2");
  });

  it("says plainly when nothing has shipped", () => {
    render(<ShippingStatus features={[{ ...features[1] }]} />);
    expect(screen.getByText(/Nothing yet/)).toBeInTheDocument();
  });

  it("shows an unavailable state when the API cannot be reached", () => {
    render(<ShippingStatus features={null} />);
    expect(screen.getByRole("status")).toHaveTextContent("not reachable");
  });
});
