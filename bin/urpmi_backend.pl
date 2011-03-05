#!/usr/bin/perl

use warnings;
use strict;

use URPM;
use urpm;
use urpm::media;
use urpm::args;
use urpm::select;

$| = 1;

my %routine = (
    'do-nothing' => sub { print "\n" },
    'list-media' => \&list_media
);

my $urpm = urpm->new_parse_cmdline;
urpm::media::configure($urpm);

while (<>) {
    chomp($_);
    $_ or $_ = 'do-nothing';
    my ($cmd, @args) = split /\s+/, $_;
    exists $routine{$cmd} or die "Unknow command $cmd\n";
    $routine{$cmd}->(@args);
}

sub to_bool {
    return $_[0] ? 'True' : 'False';
}

sub list_media {
    foreach (@{$urpm->{media}}) {
	my ($name, $update, $ignore) 
	    = ($_->{name}, $_->{update}, $_->{ignore});
	printf("('%s', %s, %s)\n", $name, to_bool($update), to_bool($ignore))
    }
    print "\n";
}
