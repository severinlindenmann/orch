import SwiftUI
import Charts

struct BlocksView: View {
    let result: BlocksResult
    var fromLabel: String? = nil
    var showsSourceLabel = true
    var showsTitle = true
    var fileAttachment: ((String) -> TicketSnapshot.Attachment?)? = nil
    var onOpenAttachment: ((TicketSnapshot.Attachment) -> Void)? = nil

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            switch result {
            case .invalid(let raw):
                VStack(alignment: .leading, spacing: 10) {
                    Text(verbatim: "These results can't be shown")
                    DisclosureGroup {
                        Text(verbatim: raw).font(.system(.caption, design: .monospaced)).textSelection(.enabled)
                    } label: { Text(verbatim: "Details") }
                }
            case .shown(let doc):
                if showsSourceLabel { Text(verbatim: fromLabel ?? doc.fromLabel).themeFont(11).foregroundStyle(Theme.muted) }
                if showsTitle, let title = doc.title { Text(verbatim: title).themeFont(20, .semibold) }
                ForEach(doc.rows.indices, id: \.self) { index in row(doc.rows[index]) }
            }
        }
        .themeFont(14).foregroundStyle(Theme.text)
        .frame(maxWidth: .infinity, alignment: .leading)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("blocks-view")
    }

    /// At most `n` axis values, evenly strided from the first (one mark per distinct value could mean 800 labels).
    nonisolated static func ticks<T>(_ v: [T], max n: Int = 6) -> [T] {
        guard n > 0, v.count > n else { return n > 0 ? v : [] }
        let step = (v.count + n - 1) / n
        return Swift.stride(from: 0, to: v.count, by: step).map { v[$0] }
    }

    private func tone(_ name: String?) -> Color {
        switch name { case "good": Theme.brand; case "warn": Theme.warn; case "bad": Theme.danger; default: Theme.text }
    }
    private func stateIcon(_ state: String?) -> String {
        switch state {
        case "running": "arrow.triangle.2.circlepath"
        case "done": "checkmark.circle"
        case "failed": "xmark.circle"
        case "skipped": "minus.circle"
        default: "circle.dotted"
        }
    }
    @ViewBuilder private func heading(_ b: BlockFields) -> some View {
        if let title = b.text("title") { Text(verbatim: title).themeFont(15, .semibold) }
    }
    @ViewBuilder private func row(_ row: BlockRow) -> some View {
        switch row {
        case .unsupported:
            Text(verbatim: "can't show this here").foregroundStyle(Theme.muted).accessibilityIdentifier("blocks-unsupported")
        case .summary(let b):
            Text(verbatim: b.text("text") ?? "").foregroundStyle(tone(b.text("tone")))
        case .steps(let b):
            let items = b.objects("items")
            VStack(alignment: .leading, spacing: 8) {
                ForEach(items.indices, id: \.self) { i in
                    HStack(alignment: .top) {
                        Image(systemName: stateIcon(items[i].text("state")))
                            .foregroundStyle(items[i].text("state") == "failed" ? Theme.danger : Theme.muted)
                            .accessibilityLabel(Text(verbatim: items[i].text("state") ?? ""))
                        VStack(alignment: .leading) {
                            Text(verbatim: items[i].text("label") ?? "")
                            if let note = items[i].text("note") { Text(verbatim: note).foregroundStyle(Theme.muted) }
                        }
                    }
                }
            }
        case .progress(let b):
            VStack(alignment: .leading, spacing: 6) {
                Text(verbatim: b.text("label") ?? "")
                if let total = b.number("total") {
                    // Normalize before converting: contract numbers may exceed Int or be fractional.
                    ProgressBar(done: Int(min(1, max(0, (b.number("done") ?? 0) / total)) * 10_000), total: 10_000)
                } else { ProgressView() }
                Text(verbatim: b.progressText).foregroundStyle(Theme.muted)
            }
        case .stat(let b):
            VStack(alignment: .leading, spacing: 4) {
                Text(verbatim: b.statText).themeFont(28, .semibold).foregroundStyle(tone(b.text("tone")))
                Text(verbatim: b.text("label") ?? "")
                if let delta = b.text("delta") { Text(verbatim: delta).foregroundStyle(Theme.muted) }
            }
        case .kv(let b):
            let items = b.objects("items")
            Grid(alignment: .leading, horizontalSpacing: 16, verticalSpacing: 8) {
                ForEach(items.indices, id: \.self) { i in
                    GridRow {
                        Text(verbatim: items[i].text("key") ?? "").foregroundStyle(Theme.muted)
                        Text(verbatim: BlocksFormat.cell(items[i].values["value"]))
                    }
                }
            }
        case .table(let b): table(b)
        case .file(let b):
            let name = (b.text("path") ?? "").components(separatedBy: "/").last ?? ""
            let attachment = fileAttachment?(name)
            if let attachment, let onOpenAttachment {
                Button { onOpenAttachment(attachment) } label: { file(b, attachment: attachment) }
                    .buttonStyle(.plain).accessibilityLabel(Text(verbatim: b.fileName))
            } else { file(b, attachment: attachment) }
        case .link(let b):
            if let url = SafeLink.url(b.text("url")), url.scheme == "https", url.user == nil, url.password == nil {
                Link(destination: url) { Text(verbatim: b.text("label") ?? "") }.foregroundStyle(Theme.brand)
            } else {
                // A link SafeLink refuses still shows its label, muted and not tappable.
                Text(verbatim: b.text("label") ?? "").foregroundStyle(Theme.muted)
            }
        case .log(let b):
            VStack(alignment: .leading, spacing: 6) {
                heading(b)
                ForEach(b.list("lines").indices, id: \.self) { i in
                    Text(verbatim: b.list("lines")[i].string ?? "").font(.system(.caption, design: .monospaced))
                }
                if b.number("cut") != nil { Text(verbatim: "Cut").foregroundStyle(Theme.muted) }
            }.frame(maxWidth: .infinity, alignment: .leading).padding(12).themeCard(fill: Theme.surface)
        case .chart(let b): BlocksChart(block: b)
        }
    }

    private func file(_ b: BlockFields, attachment: TicketSnapshot.Attachment?) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Image(systemName: "doc").accessibilityHidden(true)
                Text(verbatim: b.fileName)
                if let size = b.sizeText { Text(verbatim: size).foregroundStyle(Theme.muted) }
            }
            if b.text("preview") == "image", attachment?.kind == "image", let blobId = attachment?.blobId {
                BlobImage(id: blobId).frame(height: 160)
                    .clipShape(RoundedRectangle(cornerRadius: Theme.Radius.s))
                    .accessibilityHidden(true)
            }
        }
    }

    private func numericColumn(_ column: BlockFields, rows: [BlockFields]) -> Bool {
        if ["number", "duration"].contains(column.text("kind") ?? "") { return true }
        let key = column.text("key") ?? ""
        return rows.contains { $0.values[key]?.number != nil }
    }

    private func table(_ b: BlockFields) -> some View {
        let columns = b.objects("columns"), rows = b.objects("rows")
        return VStack(alignment: .leading, spacing: 8) {
            heading(b)
            ScrollView(.horizontal) {
                Grid(alignment: .leading, horizontalSpacing: 20, verticalSpacing: 8) {
                    GridRow {
                        ForEach(columns.indices, id: \.self) { i in
                            Text(verbatim: columns[i].text("label") ?? "").themeFont(13, .semibold)
                                .gridColumnAlignment(numericColumn(columns[i], rows: rows) ? .trailing : .leading)
                        }
                    }
                    ForEach(rows.indices, id: \.self) { r in
                        GridRow {
                            ForEach(columns.indices, id: \.self) { c in
                                let value = rows[r].values[columns[c].text("key") ?? ""]
                                Text(verbatim: BlocksFormat.cell(value, kind: columns[c].text("kind")))
                                    .foregroundStyle(columns[c].text("kind") == "tone" ? tone(value?.string) : Theme.text)
                                    .gridCellAnchor(numericColumn(columns[c], rows: rows) || value?.number != nil ? .trailing : .leading)
                            }
                        }
                    }
                }
            }
            if let footer = b.tableFooter { Text(verbatim: footer).themeFont(12).foregroundStyle(Theme.muted) }
        }
    }
}

private struct BlocksChart: View {
    let block: BlockFields
    private struct Point: Identifiable {
        let id: String
        let series: String
        let segment: String
        let x: BlockValue
        let y: Double
    }
    private var points: [Point] {
        block.objects("series").enumerated().flatMap { index, series in
            var segment = 0
            return series.list("points").enumerated().compactMap { offset, value -> Point? in
                let pair = value.array
                guard pair.count == 2, let y = pair[1].number else { segment += 1; return nil }
                return Point(id: "\(index)-\(offset)", series: series.text("name") ?? "", segment: "\(index)-\(segment)", x: pair[0], y: y)
            }
        }
    }
    private var allPairs: [[BlockValue]] { block.objects("series").flatMap { $0.list("points").map(\.array) } }
    private var numericX: Bool { allPairs.allSatisfy { $0.first?.number != nil } }
    private var xNumbers: [Double] { Array(Set(allPairs.compactMap { $0.first?.number })).sorted() }
    private var xStrings: [String] {
        var seen = Set<String>()
        return allPairs.map { BlocksFormat.cell($0.first) }.filter { seen.insert($0).inserted }
    }
    private var yNumbers: [Double] { Array(Set(points.map(\.y))).sorted() }
    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            if let title = block.text("title") { Text(verbatim: title).themeFont(15, .semibold) }
            if let y = block.text("y_label") { Text(verbatim: y).foregroundStyle(Theme.muted) }
            Chart(points) { point in
                if numericX, let x = point.x.number {
                    if block.text("kind") == "bar" {
                        BarMark(x: .value("x", x), y: .value("y", point.y)).foregroundStyle(by: .value("Series", point.series))
                    } else {
                        LineMark(x: .value("x", x), y: .value("y", point.y), series: .value("Segment", point.segment))
                            .foregroundStyle(by: .value("Series", point.series))
                    }
                } else {
                    if block.text("kind") == "bar" {
                        BarMark(x: .value("x", BlocksFormat.cell(point.x)), y: .value("y", point.y)).foregroundStyle(by: .value("Series", point.series))
                    } else {
                        LineMark(x: .value("x", BlocksFormat.cell(point.x)), y: .value("y", point.y), series: .value("Segment", point.segment))
                            .foregroundStyle(by: .value("Series", point.series))
                    }
                }
            }
            .chartLegend(.hidden)
            .chartXAxis {
                if numericX {
                    AxisMarks(values: BlocksView.ticks(xNumbers)) { value in
                        AxisGridLine()
                        AxisValueLabel { Text(verbatim: value.as(Double.self).map(BlocksFormat.number) ?? "") }
                    }
                } else {
                    AxisMarks(values: BlocksView.ticks(xStrings)) { value in
                        AxisGridLine()
                        AxisValueLabel { Text(verbatim: value.as(String.self) ?? "") }
                    }
                }
            }
            .chartYAxis {
                AxisMarks(values: BlocksView.ticks(yNumbers)) { value in
                    AxisGridLine()
                    AxisValueLabel { Text(verbatim: value.as(Double.self).map(BlocksFormat.number) ?? "") }
                }
            }
            .frame(height: 180)
            .accessibilityLabel(Text(verbatim: block.chartLabel))
            if let x = block.text("x_label") { Text(verbatim: x).foregroundStyle(Theme.muted) }
            let series = block.objects("series")
            ForEach(series.indices, id: \.self) { i in Text(verbatim: series[i].text("name") ?? "") }
        }
    }
}
