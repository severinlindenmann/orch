import XCTest

extension XCUIApplication {
    /// Scrolls a list row up until it sits clear of the pinned "New topic" bar at the bottom (a row under the bar still counts as
    /// "hittable", but a tap or swipe at its centre lands on the bar and opens the New topic sheet).
    func reveal(_ row: XCUIElement) {
        let bar = buttons["New topic"]
        for _ in 0..<5 {
            let limit = bar.exists ? bar.frame.minY - 24 : frame.maxY - 24
            if row.exists, row.frame.midY < limit, row.frame.midY > 0 { return }
            swipeUp()
        }
    }

    /// Scrolls up until the WHOLE element is on screen and clear of the home-indicator strip. `isHittable` only checks the
    /// centre: a box half under the bottom edge is "hittable", but a tap near its edge lands in the system gesture area.
    func revealWhole(_ element: XCUIElement, margin: CGFloat = 44) {
        for _ in 0..<8 {
            let f = element.frame
            if element.exists, f.minY > 0, f.maxY < frame.maxY - margin { return }
            swipeUp()
        }
    }
}
