//! Minimal bounded Casulo shell parser/dispatcher.
//!
//! The preview intentionally exposes read-only commands only. The parser has
//! no allocation, no prefix matching and no command capable of mutating disks,
//! firmware, page tables or scheduler state.

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum Command {
    Help,
    Status,
    Topology,
    Scheduler,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ParseError {
    Empty,
    TooLong,
    NonAscii,
    Unknown,
}

pub struct Reply {
    pub command: Command,
    pub text: &'static str,
}

pub fn parse(input: &[u8]) -> Result<Command, ParseError> {
    if input.is_empty() {
        return Err(ParseError::Empty);
    }
    if input.len() > 16 {
        return Err(ParseError::TooLong);
    }
    if !input.is_ascii() {
        return Err(ParseError::NonAscii);
    }
    match input {
        b"help" => Ok(Command::Help),
        b"status" => Ok(Command::Status),
        b"topology" => Ok(Command::Topology),
        b"scheduler" => Ok(Command::Scheduler),
        _ => Err(ParseError::Unknown),
    }
}

pub fn dispatch(command: Command) -> Reply {
    let text = match command {
        Command::Help => "help status topology scheduler",
        Command::Status => "research-preview bounded read-only",
        Command::Topology => "query serial boot topology markers",
        Command::Scheduler => "query logical scheduler markers",
    };
    Reply { command, text }
}

pub fn self_test() -> bool {
    let fixtures = [
        (
            b"help".as_slice(),
            Command::Help,
            "help status topology scheduler",
        ),
        (
            b"status".as_slice(),
            Command::Status,
            "research-preview bounded read-only",
        ),
        (
            b"topology".as_slice(),
            Command::Topology,
            "query serial boot topology markers",
        ),
        (
            b"scheduler".as_slice(),
            Command::Scheduler,
            "query logical scheduler markers",
        ),
    ];
    let accepted = fixtures.into_iter().all(|(raw, expected, text)| {
        let Ok(command) = parse(raw) else {
            return false;
        };
        let reply = dispatch(command);
        reply.command == expected && reply.text == text
    });
    accepted
        && parse(b"") == Err(ParseError::Empty)
        && parse(b"shutdown") == Err(ParseError::Unknown)
        && parse(b"reboot") == Err(ParseError::Unknown)
        && parse(b"help-with-trailing-data") == Err(ParseError::TooLong)
        && parse(&[0xff]) == Err(ParseError::NonAscii)
}
