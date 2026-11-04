import SwiftUI

struct OrbitMark: View {
    var body: some View {
        GeometryReader { proxy in
            let scale = min(proxy.size.width, proxy.size.height) / 64
            ZStack {
                Circle().stroke(Theme.text, lineWidth: 6 * scale)
                    .frame(width: 40 * scale, height: 40 * scale)
                Circle().fill(Theme.brand).frame(width: 12 * scale, height: 12 * scale)
                Circle().fill(Theme.brand)
                    .overlay(Circle().stroke(Theme.sidebar, lineWidth: 3 * scale))
                    .frame(width: 14 * scale, height: 14 * scale)
                    .offset(x: 15 * scale, y: -15 * scale)
            }
            .frame(width: proxy.size.width, height: proxy.size.height)
        }
        .accessibilityHidden(true)
    }
}

struct Brand: View {
    var body: some View {
        HStack(spacing: 8) {
            OrbitMark().frame(width: 30, height: 30)
            Text("orch").font(.system(size: 23, weight: .bold)).tracking(-1)
        }
    }
}

struct PrimaryButtonStyle: ButtonStyle {
    @Environment(\.isEnabled) private var enabled
    func makeBody(configuration: Configuration) -> some View {
        configuration.label.font(.system(size: 14, weight: .semibold))
            .frame(maxWidth: .infinity, minHeight: 48)
            .foregroundStyle(Theme.onBrand)
            .background(Theme.brand, in: RoundedRectangle(cornerRadius: 8))
            .opacity(enabled ? (configuration.isPressed ? 0.8 : 1) : 0.5)
    }
}

struct SecondaryButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label.font(.system(size: 14))
            .frame(maxWidth: .infinity, minHeight: 46)
            .foregroundStyle(Theme.text)
            .background(configuration.isPressed ? Theme.surface3 : Theme.surface2,
                        in: RoundedRectangle(cornerRadius: 8))
            .overlay(RoundedRectangle(cornerRadius: 8).stroke(Theme.border))
    }
}

extension View {
    func orchCard(border: Color = Theme.border, padding: CGFloat = 16) -> some View {
        self.padding(padding).frame(maxWidth: .infinity, alignment: .leading)
            .background(Theme.surface, in: RoundedRectangle(cornerRadius: 10))
            .overlay(RoundedRectangle(cornerRadius: 10).stroke(border))
    }
}

struct Eyebrow: View {
    let text: String
    var color: Color = Theme.muted
    var body: some View {
        Text(text).font(.system(size: 10, weight: .semibold)).tracking(1.2).foregroundStyle(color)
    }
}

struct ScreenHeading: View {
    let title: String
    let subtitle: String
    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(title).font(.system(size: 29, weight: .semibold)).tracking(-1.1)
                .accessibilityAddTraits(.isHeader)
            Text(subtitle).font(.system(size: 13)).foregroundStyle(Theme.muted)
        }
    }
}

struct WorkspaceBackHeader: View {
    @Environment(AppModel.self) private var model
    var body: some View {
        HStack {
            Button { model.tab = .home } label: {
                Text("‹ Workspaces").font(.system(size: 12)).frame(minHeight: 44)
            }.foregroundStyle(Theme.muted)
            Spacer()
            OrbitMark().frame(width: 27, height: 27)
        }.padding(.bottom, 28)
    }
}

struct ModelMessage: View {
    @Environment(AppModel.self) private var model
    var body: some View {
        if let message = model.message {
            Text(message).font(.caption).foregroundStyle(Theme.danger)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
    }
}
